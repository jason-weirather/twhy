"""Viewer scheduling and text histogram interaction above the reusable estimator."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import replace

import numpy as np
from prompt_toolkit.mouse_events import MouseButton, MouseEventType

from ..contrast import ContrastConfig, ContrastEstimator
from ..histogram import render_histogram
from .rendering import terminal_lines
from .controls import safe_label


class ContrastController:
    """One incremental job on the existing display worker; no parallel pixel reader."""

    def __init__(self, viewer, *, config=None, automatic=True, explicit_window=False):
        self.viewer = viewer
        self.config = config or ContrastConfig()
        self.automatic = automatic
        self.explicit_window = explicit_window
        self.key = None
        self.source = None
        self.results = OrderedDict()
        self.completed = set()
        # Windows outlive histogram payload eviction. The cache fits at least one
        # explicitly enlarged experiment, otherwise defaults to 32 MiB.
        self.cache_budget = max(32 * 1024 * 1024,
                                self.config.max_base_samples * 16 +
                                (2 * self.config.histogram_bins + 1) * 8)
        self.errors = {}
        self.manual = set()
        self.revisions = {}
        self.queue = OrderedDict()
        self.job = None
        self.owner = None
        self.job_revision = 0
        self.job_apply = False
        self.deferred = None
        self.plot = None
        self._plot_key = None
        self._lines = []
        self.drag = None
        self.log_counts = True

    def sync_source(self):
        nav = self.viewer.navigation
        source = (nav.active.dataset if nav is not None and nav.active.dataset is not None
                  else getattr(self.viewer.session, "_image", None))
        key = (getattr(source, "identity", None) if callable(getattr(source, "read_block", None))
               else id(self.viewer.session))
        if key == self.key:
            return
        self.close_job()
        self.key, self.source = key, source
        self.results.clear()
        self.completed.clear()
        self.errors.clear()
        self.queue.clear()
        self.manual = set(range(len(self.viewer.windows))) if self.explicit_window else set()
        self.revisions.clear()
        self.deferred = None
        self.plot = self._plot_key = self.drag = None

    def protect(self, channel):
        self.sync_source()
        self.manual.add(channel)
        if channel in self.queue:
            # An automatic request queued before a manual edit may still produce
            # a histogram, but must not apply its limits when it starts later.
            self.queue[channel] = False
        self.revisions[channel] = self.revisions.get(channel, 0) + 1

    def request(self, channel, *, apply=False, force=False):
        self.sync_source()
        if self.source is None:
            self.errors[channel] = "This embedded session has no image provider for sampling."
            return
        if force:
            self.errors.pop(channel, None)
        if channel in self.results:
            self.results.move_to_end(channel)
            if apply:
                self._apply(channel, self.results[channel])
            return
        if channel in self.errors:
            return
        if self.job is not None and self.job._source.channel == channel:
            if apply:
                self.job_apply = True
                self.job_revision = self.revisions.get(channel, 0)
            return
        self.queue[channel] = self.queue.get(channel, False) or apply
        if self.viewer._wake is not None:
            self.viewer._wake.set()

    def queue_automatic(self):
        self.sync_source()
        nav = self.viewer.navigation
        is_stack = (nav is not None and nav.active.dataset is not None and
                    any(axis.size > 1 for axis in nav.active.axis_info))
        if self.automatic and is_stack and not self.viewer.session.info.is_rgb:
            for channel in self.viewer.selected_channels:
                if channel not in self.manual and channel not in self.completed:
                    self.request(channel, apply=True)
        if self.viewer.histogram_mode:
            self.request(self.viewer.focused_channel)

    def _apply(self, channel, result):
        if result.window is None:
            return
        current = self.viewer.windows[channel]
        gamma = 1. if current is None else current.gamma
        self.viewer.windows[channel] = replace(result.window, gamma=gamma)
        self.viewer.message = (f"C{channel}: {result.scope} contrast estimated and locked "
                               f"({result.unique_tiles} tiles; {result.policy}).")
        if channel in self.viewer.selected_channels:
            self.viewer.request_frame(reuse_samples=True)

    def apply_auto(self):
        channel = self.viewer.focused_channel
        self.manual.discard(channel)
        self.request(channel, apply=True, force=True)
        self.viewer.application.invalidate()

    async def step(self):
        """Foreground navigation/rendering calls this only when no frame is queued."""
        viewer = self.viewer
        self.queue_automatic()
        if self.deferred is not None and not viewer.selecting and viewer.editing is None:
            channel, result, revision = self.deferred
            self.deferred = None
            if self.revisions.get(channel, 0) == revision:
                self._apply(channel, result)
                return True
        if self.job is None:
            if not self.queue:
                return False
            channel, apply = self.queue.popitem(last=False)
            nav = viewer.navigation
            self.owner = nav.active.retain() if nav is not None else None
            try:
                self.job = ContrastEstimator(self.source, channel=channel, config=self.config)
            except Exception as error:
                self.errors[channel] = str(error)
                self.close_job()
                viewer.application.invalidate()
                return bool(self.queue)
            self.job_revision = self.revisions.get(channel, 0)
            self.job_apply = apply
        job = self.job
        channel = job._source.channel
        try:
            more = await asyncio.get_running_loop().run_in_executor(viewer._executor, job.step)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.errors[channel] = str(error)
            viewer.message = f"Contrast C{channel} failed: {error}"
            self.close_job()
            viewer.application.invalidate()
            return bool(self.queue)
        if not more:
            result, revision, apply = job.result, self.job_revision, self.job_apply
            self._store_result(channel, result)
            self.close_job()
            if apply and self.revisions.get(channel, 0) == revision:
                if viewer.selecting or viewer.editing is not None:
                    self.deferred = channel, result, revision
                else:
                    self._apply(channel, result)
        viewer.application.invalidate()
        return more or bool(self.queue)

    @property
    def cache_bytes(self):
        return sum(result.nbytes for result in self.results.values())

    def _store_result(self, channel, result):
        self.results[channel] = result
        self.results.move_to_end(channel)
        self.completed.add(channel)
        while self.cache_bytes > self.cache_budget and len(self.results) > 1:
            self.results.popitem(last=False)

    @property
    def status(self):
        if self.job is None:
            return ""
        p = self.job.progress
        return (f"contrast C{self.job._source.channel}: {p['phase']} "
                f"{p['base_draws']}/{p['planned_draws']}")

    def content(self, width, height):
        """Only uses detached results. Never reads pixels from paint callbacks."""
        channel = self.viewer.focused_channel
        estimate = self.results.get(channel)
        if estimate is None:
            message = self.errors.get(channel, self.status or "Contrast sampling queued...")
            self.plot = None
            return [[("class:panel.title", f" Histogram C{channel}")],
                    [("class:status", " " + safe_label(message))],
                    [("class:status", " H: image | A: estimate/apply | l/u: limits")]]
        self.results.move_to_end(channel)
        window = self.viewer.windows[channel] or estimate.window
        renderer = self.viewer.renderer
        use_color = renderer.color and self.viewer.mode_navigation.family != "ascii"
        color = tuple(self.viewer.channel_colors[channel]) if use_color else None
        key = (id(estimate), window, width, height, self.log_counts, color,
               self.viewer.mode_navigation.family)
        if key != self._plot_key:
            self.plot = render_histogram(estimate, window=window, columns=width, rows=height,
                                         log_counts=self.log_counts, color=color,
                                         ascii_only=self.viewer.mode_navigation.family == "ascii")
            self._lines = terminal_lines(self.plot.frame)
            self._plot_key = key
        return self._lines

    def mouse(self, event):
        viewer, plot = self.viewer, self.plot
        if plot is None or plot.handle_row < 0 or viewer.editing is not None:
            return
        x, y = event.position.x, event.position.y
        if event.event_type == MouseEventType.MOUSE_DOWN and event.button == MouseButton.LEFT:
            if abs(y - plot.handle_row) <= 1:
                distances = (abs(x - plot.lower_column), abs(x - plot.upper_column))
                if min(distances) <= 3:
                    field = "lower" if distances[0] <= distances[1] else "upper"
                    # Freeze both channel and mapping for the entire drag.
                    self.drag = viewer.focused_channel, field, plot
                    self.protect(viewer.focused_channel)
        if event.event_type in (MouseEventType.MOUSE_MOVE, MouseEventType.MOUSE_UP):
            if self.drag is not None:
                channel, field, mapping = self.drag
                if channel == viewer.focused_channel:
                    current = viewer.windows[channel] or self.results[channel].window
                    if current is not None:
                        value = mapping.value_at(x)
                        value = (min(value, float(np.nextafter(current.upper, -np.inf)))
                                 if field == "lower" else
                                 max(value, float(np.nextafter(current.lower, np.inf))))
                        viewer.windows[channel] = replace(current, **{field: value})
                        viewer.request_frame(reuse_samples=True)
                        viewer.application.invalidate()
            if event.event_type == MouseEventType.MOUSE_UP:
                self.drag = None

    def close_job(self):
        if self.job is not None:
            self.job.close()
            self.job = None
        if self.owner is not None:
            self.owner.release()
            self.owner = None

    def close(self):
        self.close_job()
        self.queue.clear()
        self.results.clear()
        self.deferred = None
        self.plot = None
        self._lines = []
