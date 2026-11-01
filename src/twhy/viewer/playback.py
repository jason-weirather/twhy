"""Slideshow clock for animated GIFs and OME time series.

Frames advance only after the previous frame has been *presented*. A slow read
stretches the dwell time: playback never skips observations or accumulates an
unbounded queue to catch up with wall time. This is not acquisition-time replay.
"""

from __future__ import annotations

import asyncio
from math import isfinite


DEFAULT_TIME_FPS = 2.0
MIN_FPS = 0.1
MAX_FPS = 30.0


def playback_rate(fps: float | None) -> float | None:
    if fps is None:
        return None
    if isinstance(fps, bool) or not isinstance(fps, (int, float)) or not isfinite(fps):
        raise ValueError("Playback FPS must be a finite number")
    if not MIN_FPS <= fps <= MAX_FPS:
        raise ValueError(f"Playback FPS must be between {MIN_FPS:g} and {MAX_FPS:g}")
    return float(fps)


class PlaybackController:
    """Event-loop-owned presentation-paced playback; no new rendering or decoding pool."""

    def __init__(self, viewer, *, fps=None, autoplay=None):
        self.viewer = viewer
        nav = viewer.navigation
        doc = None if nav is None else nav.document
        if doc is not None and doc.kind == "gif" and doc.count > 1:
            self.kind = "gif"
        elif nav is not None and any(
            axis.name == "T" and axis.size > 1 for axis in nav.active.axis_info
        ):
            self.kind = "time"
        else:
            self.kind = None
        self.fps = playback_rate(fps)
        if (fps is not None or autoplay is not None) and self.kind is None:
            raise ValueError("Playback requires an animated GIF or OME time axis")
        self.playing = bool(self.kind == "gif") if autoplay is None else bool(autoplay)
        self._last_position = None
        self._deadline: float | None = None
        self._ready = False
        self._event: asyncio.Event | None = None
        self._advancing = False
        self._closed = False

    @property
    def available(self) -> bool:
        return self.kind is not None

    @property
    def rate_label(self) -> str:
        if self.fps is not None:
            return f"{self.fps:g} fps"
        return "GIF delay" if self.kind == "gif" else f"{DEFAULT_TIME_FPS:g} fps"

    def _duration(self, frame: int) -> float:
        if self.fps is not None:
            return 1 / self.fps
        if self.kind == "gif":
            return self.viewer.navigation.document.animation.duration(frame)
        return 1 / DEFAULT_TIME_FPS

    def _wake(self):
        if self._event is not None:
            self._event.set()
        app = self.viewer.application
        if app is not None:
            app.invalidate()

    def start(self) -> None:
        self._event = asyncio.Event()

    def pause(self) -> None:
        if self.playing:
            self.playing = False
            self._deadline = None
            self._wake()

    def toggle(self) -> None:
        if not self.available or self.viewer.selecting or self.viewer.editing is not None:
            return
        if self.playing:
            self.pause()
        else:
            nav = self.viewer.navigation
            if self.kind == "time":
                nav.axis = "T"
            self.playing = True
            if self._ready:
                self._deadline = asyncio.get_running_loop().time() + self._duration(
                    nav.display_position[0] if self.kind == "gif" else nav.display_position[2]
                )
            self._wake()

    def set_fps(self, fps: float) -> None:
        if not self.available:
            raise ValueError("This image has no playback dimension")
        self.fps = playback_rate(fps)
        if self._ready and self.playing:
            position = self.viewer.navigation.display_position
            self._deadline = asyncio.get_running_loop().time() + self._duration(
                position[0] if self.kind == "gif" else position[2]
            )
        self._wake()

    def presented(self, position) -> None:
        """Called only after a complete matching frame and label are published."""
        if not self.available:
            return
        if position != self._last_position:
            self._last_position = position
            self._deadline = asyncio.get_running_loop().time() + self._duration(
                position[0] if self.kind == "gif" else position[2]
            )
        self._ready = True
        self._wake()

    async def run(self) -> None:
        if not self.available:
            return
        if self._event is None:
            self.start()
        loop = asyncio.get_running_loop()
        while not self._closed:
            nav = self.viewer.navigation
            if (not self.playing or not self._ready or self.viewer.selecting or
                    self.viewer.editing is not None or self.viewer.histogram_mode or
                    nav.loading or nav.pending is not None or nav.presentation_pending or
                    self.viewer.busy or self.viewer._pending is not None):
                await self._event.wait()
                self._event.clear()
                continue
            deadline = self._deadline
            if deadline is None:
                deadline = loop.time() + self._duration(
                    nav.display_position[0] if self.kind == "gif" else nav.display_position[2]
                )
                self._deadline = deadline
            seconds = deadline - loop.time()
            if seconds > 0:
                try:
                    await asyncio.wait_for(self._event.wait(), timeout=seconds)
                    self._event.clear()
                    continue
                except asyncio.TimeoutError:
                    pass
            self._ready = False
            self._deadline = None
            self._advancing = True
            try:
                if self.kind == "gif":
                    nav.go((nav.target + 1) % nav.document.count)
                else:
                    info = next(a for a in nav.active.axis_info if a.name == "T")
                    nav.go_plane(z_index=nav.target_z,
                                 t_index=(nav.target_t + 1) % info.size)
            except (ValueError, RuntimeError):
                self.pause()
            finally:
                self._advancing = False

    def close(self) -> None:
        self._closed = True
        self._wake()
