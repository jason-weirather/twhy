"""Dimension-focused navigation and safe source handoffs for the existing UI."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

from .._validation import positive_integer
from ..image_document import DocumentItem, ImageDocument
from ..pdf_workers import DEFAULT_PDF_CACHE_PAGES, PdfWorkers
from ..view_info import ReadBudgetExceeded
from ..view_session import ViewSession
from ..runtime_overview import DEFAULT_OVERVIEW_CACHE_MIB, DEFAULT_OVERVIEW_MAX_SOURCE_PIXELS
from ..viewport import Viewport

if TYPE_CHECKING:
    from .viewer import Viewer


class DocumentNavigation:
    """Event-loop-owned selection, RAM cache, and progressive source handoff.

    Source swaps run only inside Viewer's one render pump, between reads. A new
    ViewSession means no stale preview cache can survive a source/DPI change.
    Only the best completed pyramid per cached page is retained. The active
    image holds a separate reference until its final render has finished.
    """

    def __init__(self, document: ImageDocument, initial: DocumentItem, *,
                 cache_pages: int = DEFAULT_PDF_CACHE_PAGES, cache_mib: float = 32,
                 max_read_pixels: int = 4_194_304, window=None, auto_invert: bool = False,
                 overview_cache_mib: float = DEFAULT_OVERVIEW_CACHE_MIB,
                 overview_max_source_pixels: int = DEFAULT_OVERVIEW_MAX_SOURCE_PIXELS) -> None:
        self.document = document
        self.cache_pages = positive_integer(cache_pages, "pdf_cache_pages")
        self.cache_mib, self.max_read_pixels = cache_mib, max_read_pixels
        self.overview_cache_mib = overview_cache_mib
        self.overview_max_source_pixels = overview_max_source_pixels
        self.default_window, self.auto_invert = window, auto_invert
        self.active = initial
        self.session = self._session(initial)
        self.target = initial.index
        self.target_z, self.target_t = initial.z_index, initial.t_index
        self._target_auto = False
        self.axis = self.axes[0]
        self.viewer: Viewer | None = None
        self.cache: OrderedDict[int, DocumentItem] = OrderedDict()
        self.pending: DocumentItem | None = None
        self.error = ""
        self.building: set[tuple[int, float, int]] = set()
        self._blocked_upgrade = None
        self._epoch = 0
        self._started_epoch = -1
        self._closed = False
        self._released = False
        self._wake: asyncio.Event | None = None
        self._loader: ThreadPoolExecutor | None = None
        self._load_task: asyncio.Task | None = None
        self._refine_task: asyncio.Task | None = None
        self._tasks: set[asyncio.Task] = set()
        self._workers: PdfWorkers | None = None
        self._remember(initial)

    def _session(self, item: DocumentItem) -> ViewSession:
        return ViewSession(item.image, name=self.document.item_name(item),
                           cache_mib=self.cache_mib, max_read_pixels=self.max_read_pixels,
                           overview_cache_mib=self.overview_cache_mib,
                           overview_max_source_pixels=self.overview_max_source_pixels)

    @property
    def cache_bytes(self) -> int:
        return sum(item.nbytes for item in self.cache.values())

    @property
    def axes(self) -> tuple[str, ...]:
        """Only independently navigable dimensions; ordinary documents keep theirs."""
        if self.document.kind == "pdf":
            return ("page",)
        dimensions = tuple(axis.name for axis in self.active.axis_info if axis.size > 1)
        return dimensions + (("series",) if self.document.count > 1 or not dimensions else ())

    @property
    def target_position(self):
        return self.target, self.target_z, self.target_t

    def _matches_target(self, item):
        return (item.index == self.target and
                (self._target_auto or item.position == self.target_position))

    @property
    def loading(self) -> bool:
        return not self._matches_target(self.active)

    @property
    def destination_label(self) -> str:
        return {"Z": "Z plane", "T": "time point"}.get(self.axis, self.document.label)

    @property
    def destination_limits(self) -> tuple[int, int]:
        if self.axis in ("Z", "T"):
            axis = next(axis for axis in self.active.axis_info if axis.name == self.axis)
            return 0, axis.size - 1
        return self.document.first_index, self.document.last_index

    def select_axis(self, axis: str) -> None:
        if self._closed or self.viewer is None or self.viewer.selecting:
            return
        if self.viewer.editing is not None:
            return
        if axis not in self.axes:
            raise ValueError(f"Unavailable navigation dimension: {axis}")
        if self.target != self.active.index and axis in ("Z", "T"):
            self.viewer.message = "The requested series is opening; its Z/T controls follow it."
        else:
            self.axis = axis
            self.viewer.message = f"Navigate {self.destination_label}: [ / ] to step; p to jump."
        self._invalidate()

    def cycle_axis(self) -> None:
        axes = self.axes
        self.select_axis(axes[(axes.index(self.axis) + 1) % len(axes)])

    def validate_destination(self, index: int) -> int:
        from ..image_input import _index
        first, last = self.destination_limits
        index = _index(index, self.destination_label, minimum=first)
        if not first <= index <= last:
            raise ValueError(f"Choose {self.destination_label} {first}..{last}")
        return index

    def go_destination(self, index: int) -> None:
        index = self.validate_destination(index)
        if self.axis in ("Z", "T"):
            z = index if self.axis == "Z" else self.target_z
            t = index if self.axis == "T" else self.target_t
            self.go_plane(z_index=z, t_index=t)
        else:
            self.go(index)

    def go_plane(self, *, z_index=None, t_index=None) -> None:
        if (self._closed or self.viewer.selecting or
                self.target != self.active.index or self._target_auto):
            return
        # Validate entirely from the already discovered axis metadata. Never
        # open a new plane or take the backend read lock on the event loop.
        from ..image_input import _index
        indices = {"Z": z_index, "T": t_index}
        declared = {axis.name: axis for axis in self.active.axis_info}
        for name, index in indices.items():
            axis = declared.get(name)
            if axis is None:
                if index is not None:
                    raise ValueError(f"Source has no {name} axis")
            else:
                if index is None:
                    if axis.size > 1:
                        raise ValueError(f"Select {name} explicitly")
                    index = 0
                index = _index(index, name)
                if index >= axis.size:
                    raise ValueError(f"Choose {name} 0..{axis.size - 1}")
                indices[name] = index
        position = self.target, indices["Z"], indices["T"]
        if position == self.target_position:
            return
        self.target_z, self.target_t = indices["Z"], indices["T"]
        self._retarget()

    def _retarget(self) -> None:
        """Invalidate in-flight results and coalesce to one immutable destination."""
        self._epoch += 1
        self.error = ""
        self._blocked_upgrade = None
        if (self._refine_task is not None and not self._refine_task.done()
                and not self._refine_task.cancelling()):
            self._refine_task.cancel()
        if self.pending is not None:
            self.pending.release()
            self.pending = None
        self.viewer.generation += 1
        self.viewer._pending = None
        self.viewer.busy = False
        self.viewer._startup_target = None
        self.viewer._startup_generation = None
        self.viewer._startup_session = None
        if not self.loading:
            self.viewer.request_frame()
        elif self.document.kind == "pdf" and self.target in self.cache:
            self._queue(self.cache[self.target].retain())
        else:
            self._wake.set()
        self._invalidate()

    def start(self, viewer: Viewer) -> None:
        self.viewer = viewer
        self._wake = asyncio.Event()
        self._loader = ThreadPoolExecutor(max_workers=1, thread_name_prefix="twhy-source")
        self._load_task = asyncio.create_task(self._load_loop())

    def _invalidate(self) -> None:
        if self.viewer is not None and self.viewer.application is not None:
            self.viewer.application.invalidate()

    def _report_error(self, message: str) -> None:
        self.error = message
        if self.viewer is not None:
            self.viewer.message = message
        self._invalidate()

    def _upgrade_key(self, item: DocumentItem):
        view = self.viewer
        return (item.dpi, view.viewport, view.canvas_size, tuple(view.selected_channels),
                view.renderer.mode)

    def _remember(self, item: DocumentItem) -> None:
        if self.document.kind != "pdf":
            return
        previous = self.cache.get(item.index)
        if previous is not None and previous.dpi >= item.dpi:
            return
        self.cache[item.index] = item.retain()
        self.cache.move_to_end(item.index)
        if previous is not None:
            previous.release()
        while len(self.cache) > self.cache_pages:
            victim = next(index for index in self.cache if index != self.target)
            self.cache.pop(victim).release()

    def _neighbors(self) -> list[int]:
        return [index for index in (self.target + 1, self.target - 1)
                if self.document.first_index <= index <= self.document.last_index][
                    :max(0, self.cache_pages - 1)]

    def go(self, index: int) -> None:
        """Request a page/series; dimension-focused controls call go_destination."""
        index = self.document.validate_index(index)
        if self._closed or index == self.target or self.viewer.selecting:
            return
        self.target = index
        if index == self.active.index:
            self.target_z, self.target_t = self.active.z_index, self.active.t_index
            self._target_auto = False
        else:
            self.target_z = self.target_t = None
            self._target_auto = self.document.is_ome
        # Keep a small PDF neighborhood, not every page traversed so far.
        wanted = {self.target, *self._neighbors()}
        for old in tuple(self.cache):
            if old not in wanted:
                self.cache.pop(old).release()
        self._retarget()

    def step(self, delta: int) -> None:
        if self.axis in ("Z", "T") and self.target != self.active.index:
            return
        current = (self.target_z if self.axis == "Z" else
                   self.target_t if self.axis == "T" else self.target)
        first, last = self.destination_limits
        index = current + delta
        if first <= index <= last:
            self.go_destination(index)
        else:
            self.viewer.message = f"No {self.destination_label} beyond this end of the document."
            self._invalidate()

    def _queue(self, item: DocumentItem) -> None:
        """Consume a reference; newer/better sources supersede pending handoffs."""
        if self._closed or not self._matches_target(item):
            item.release()
            return
        comparison = self.pending if self.pending is not None else self.active
        if (comparison.index == item.index and item.dpi is not None
                and comparison.dpi >= item.dpi):
            item.release()
            return
        if self.pending is not None:
            self.pending.release()
        self.pending = item
        self.viewer.generation += 1
        self.viewer._pending = None
        self.viewer._wake.set()
        self._invalidate()

    async def _load_loop(self) -> None:
        while not self._closed:
            await self._wake.wait()
            self._wake.clear()
            if self._closed:
                break
            position, epoch = self.target_position, self._epoch
            index, z_index, t_index = position
            auto = self._target_auto
            if not self.loading or (self.pending is not None
                                    and self._matches_target(self.pending)):
                continue
            try:
                # One loader; repeated keys replace the requested destination,
                # including both Z and T. A queued old plane is never relabelled.
                if self.document.is_ome and not auto:
                    from functools import partial
                    load = partial(self.document.load_plane, index,
                                   z_index=z_index, t_index=t_index)
                else:
                    load = lambda index=index: self.document.load(index)
                item = await asyncio.get_running_loop().run_in_executor(self._loader, load)
            except Exception as error:
                if not self._closed and epoch == self._epoch:
                    self._report_error(f"Cannot open {self.document.label} {index}, "
                                       f"Z={z_index}, T={t_index}: {error}")
                    self.target = self.active.index
                    self.target_z, self.target_t = self.active.z_index, self.active.t_index
                    self._target_auto = False
                    self.viewer.request_frame()
                    self._invalidate()
                continue
            if self._closed or epoch != self._epoch:
                item.release()
                continue
            self.target_z, self.target_t = item.z_index, item.t_index
            self._target_auto = False
            self._remember(item)
            self._queue(item)

    def install_pending(self) -> None:
        """Called only by the render pump, after its previous read has completed."""
        if self.viewer.selecting:
            return  # Background pyramids may finish, but displayed selection stays frozen.
        item, self.pending = self.pending, None
        if item is None:
            return
        if not self._matches_target(item) or self._closed:
            item.release()
            return
        viewer = self.viewer
        old_session, old_item = self.session, self.active
        same_series = item.index == old_item.index
        plane_change = same_series and item.position != old_item.position
        same_page = same_series and self.document.kind == "pdf"
        try:
            session = self._session(item)
        except Exception as error:
            item.release()
            self._report_error(str(error))
            self.target = self.active.index
            self.target_z, self.target_t = self.active.z_index, self.active.t_index
            self._target_auto = False
            viewer.request_frame()
            return
        old_shape, new_shape = old_session.info.shape, session.info.shape
        old_view = viewer.viewport
        upgraded_view = None
        if same_page and old_view is not None:
            # PDFium rounds each raster extent independently. Preserve page-relative
            # coordinates rather than assuming an exact integer DPI scale factor.
            sy, sx = new_shape[0] / old_shape[0], new_shape[1] / old_shape[1]
            upgraded_view = Viewport(old_view.x * sx, old_view.y * sy,
                                     old_view.width * sx, old_view.height * sy)
            rows, columns = viewer.renderer.sample_shape(
                columns=viewer.canvas_size[0], rows=viewer.canvas_size[1],
            )
            try:
                session.plan(upgraded_view, rows=rows, columns=columns,
                             channels=viewer.selected_channels)
            except ReadBudgetExceeded:
                # A low custom read budget must not make an automatic detail
                # upgrade move the camera. Keep the old source; retry after the
                # next camera/mode change, not on every identical repaint.
                self._blocked_upgrade = self._upgrade_key(item)
                session.close()
                item.release()
                self._report_error("More PDF detail is cached, but this view exceeds the read "
                                   "budget. Zoom in to use it; the current view is unchanged.")
                viewer.request_frame()
                return
        if plane_change and old_view is not None:
            # Same series: exactly the same base-pixel camera and display settings.
            # The image's safe XY pyramid may vary, but Z-coarsening is never
            # selected implicitly. Budgeted sampled overviews remain available.
            upgraded_view = old_view
        if same_page and self._blocked_upgrade is not None:
            self._blocked_upgrade = None
            self.error = ""
        self.document.activate(item)
        if not same_series and viewer.editing == "destination":
            viewer.cancel_edit()
        self.session, self.active = session, item
        viewer.session = session
        viewer.samples = None
        if plane_change:
            # Do not show the previous slice under the newly installed slice label.
            viewer.frame, viewer.cell_lines = None, []
            viewer.canvas._drag = None
        if self.axis not in self.axes:
            self.axis = self.axes[0]
        if upgraded_view is not None:
            viewer.viewport = upgraded_view
        else:
            viewer.frame, viewer.cell_lines = None, []
            viewer.viewport = None
            viewer.canvas._drag = None
            if self.document.kind in {"tiff", "zarr"}:
                viewer.selected_channels = (0,)
                viewer.focused_channel = 0
                viewer.channel_control.first_channel = 0
                viewer.windows = [self.default_window] * len(session.info.channels)
                viewer.reset_channel_colors()
                if self.auto_invert:
                    # A new RGB/intensity series gets its normal default. A user
                    # density edit disables this policy in Viewer.change_renderer.
                    viewer.renderer.invert = session.info.is_rgb
        old_session.close()
        old_item.release()
        viewer.message = ("Plane changed; view, channels and contrast preserved."
                          if plane_change else
                          f"Detail ready: {item.dpi:g} DPI. Zoom and contrast preserved."
                          if same_page and item.dpi else
                          f"Opened {self.document.label} {item.index}.")
        if viewer.viewport is None:
            viewer.fit()
        elif plane_change:
            viewer.request_frame()
        else:
            viewer._set_viewport(viewer.viewport, limit=True)

    def frame_displayed(self) -> None:
        """Do not compete with the initial preview before it has reached the UI."""
        if self._closed or self.document.kind != "pdf" or self.active.index != self.target:
            return
        cached = self.cache.get(self.target)
        if (cached is not None and cached.dpi > self.active.dpi
                and self._upgrade_key(cached) != self._blocked_upgrade):
            self._queue(cached.retain())
        if self._started_epoch == self._epoch:
            return
        self._started_epoch = self._epoch
        task = asyncio.create_task(self._enrich(self.target, self._epoch))
        self._refine_task = task
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _build(self, index: int, dpi: float, epoch: int) -> None:
        key = (index, dpi, epoch)
        self.building.add(key)
        self._invalidate()
        try:
            if self._workers is None:
                self._workers = PdfWorkers()
            arrays = await self._workers.render(self.document.path, index, dpi,
                                                 self.document.background)
            if self._closed or epoch != self._epoch:
                return
            item = self.document.from_arrays(index, dpi, arrays)
            try:
                self._remember(item)
                if index == self.target:
                    self._queue(item.retain())
            finally:
                item.release()
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if not self._closed and epoch == self._epoch:
                # A failed speculative/detail render must not destroy a usable
                # lower-resolution page. The failure remains visible in the bar.
                self._report_error(str(error))
        finally:
            self.building.discard(key)
            self._invalidate()

    async def _enrich(self, index: int, epoch: int) -> None:
        try:
            completed = self.cache.get(index, self.active).dpi
            # TaskGroup waits for EVERY child's cancellation cleanup. A plain
            # gather() can propagate the first cancelled child while another
            # child's process/pipe finalizer is still running.
            async with asyncio.TaskGroup() as group:
                for dpi in self.document.dpi_steps:
                    if dpi > completed:
                        group.create_task(self._build(index, dpi, epoch))
            if self._closed or epoch != self._epoch:
                return
            current = self.cache.get(index)
            if current is None or current.dpi < self.document.dpi_steps[-1]:
                return  # No neighbor work until current-page detail succeeds.

            async def neighbor(page: int) -> None:
                for dpi in self.document.dpi_steps:
                    if self._closed or epoch != self._epoch:
                        return
                    cached = self.cache.get(page)
                    if cached is None or cached.dpi < dpi:
                        await self._build(page, dpi, epoch)

            async with asyncio.TaskGroup() as group:
                for page in self._neighbors():
                    group.create_task(neighbor(page))
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._report_error(f"PDF refinement stopped: {error}")

    def status(self, *, compact: bool = False) -> str:
        doc = self.document
        text = (f"Page {self.active.index}/{doc.count}" if doc.kind == "pdf" else
                f"Series {self.active.index} of {doc.count} (0-based)")
        for axis in self.active.axis_info:
            if axis.size > 1:
                index = self.active.z_index if axis.name == "Z" else self.active.t_index
                text += f" | {axis.name} {index}/{axis.size - 1}"
        if compact and doc.is_ome:
            text = ""
        if self.loading:
            text += f" | opening {doc.label} {self.target}"
            if self.target == self.active.index:
                text += f" Z={self.target_z} T={self.target_t}"
        if doc.kind == "pdf":
            text += f" | {self.active.dpi:g}/{doc.dpi_steps[-1]:g} DPI"
            current = sorted(dpi for page, dpi, epoch in self.building
                             if page == self.target and epoch == self._epoch)
            if current:
                text += " | building " + "/".join(f"{dpi:g}" for dpi in current)
            elif any(epoch == self._epoch for _, _, epoch in self.building):
                text += " | caching neighbors"
            text += f" | cache {len(self.cache)}/{self.cache_pages} pages"
        if self.error:
            text += f" | {self.error}"
        return text

    async def stop(self) -> None:
        """Stop work, but leave active pixels alive until the render thread joins."""
        self._closed = True
        if self._wake is not None:
            self._wake.set()
        tasks = tuple(self._tasks)
        for task in tasks:
            if not task.done() and not task.cancelling():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self._load_task is not None:
            await self._load_task  # A native quick-preview read is not thread-cancellable.
        if self._loader is not None:
            self._loader.shutdown(wait=True, cancel_futures=True)
            self._loader = None
        if self._workers is not None:
            self._workers.close()
        if self.pending is not None:
            self.pending.release()
            self.pending = None
        for item in self.cache.values():
            item.release()
        self.cache.clear()

    def close(self) -> None:
        """Release the active session only after Viewer has joined its read worker."""
        if not self._released:
            self._released = True
            self.session.close()
            self.active.release()
            self.document.close()
