"""Selection lifecycle and bounded, explicit copy/save work for the existing viewer."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ..channel_colors import apply_channel_colors
from ..geojson_clip import dumps as dump_geojson
from ..geojson_clip import geometry_feature
from ..annotation_identity import IdentityFactory
from ..selection_geometry import union_bounds
from ..image_clip import clipboard_png, write_png_clip
from ..png_clip import render_clip_png
from ..pdf_text import extract_pdf_text
from ..source_input import remote_scheme
from ..text_clip import (
    CLIPBOARD_MODES, CLIP_SOURCES, ClipboardDelivery, clipboard_delivery,
    validate_clip_path, write_text_clip,
)
from .selection_set import SelectionSet

if TYPE_CHECKING:
    from .viewer import Viewer


CLIP_EDIT_STATES = ("save-text", "save-ansi", "save-png", "save-geojson", "geojson-name")


def file_stamp(path: Path) -> tuple[int, int, int, int]:
    value = path.stat()
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


def clip_options(*, source_path=None, output_text_clip=None, output_ansi_clip=None,
                 output_png_clip=None, output_geojson_clip=None, clipboard="auto",
                 clip_source="auto", clip_overwrite=True) -> None:
    """Preflight explicit destinations without creating or truncating any file."""
    if clipboard not in CLIPBOARD_MODES or clip_source not in CLIP_SOURCES:
        raise ValueError("Invalid clipboard or clip_source option")
    paths = [Path(p).expanduser() for p in (output_text_clip, output_ansi_clip,
                                             output_png_clip, output_geojson_clip)
             if p is not None]
    source = None if source_path is None else Path(source_path)
    for path in paths:
        validate_clip_path(path, source=source, overwrite=clip_overwrite)
    for position, left in enumerate(paths):
        for right in paths[position + 1:]:
            if left.resolve() == right.resolve() or (
                left.exists() and right.exists() and left.samefile(right)
            ):
                raise ValueError(
                    "Text, ANSI, PNG and GeoJSON clip destinations must be different files"
                )


@dataclass(frozen=True)
class ClipResult:
    message: str
    delivery: ClipboardDelivery | None = None


class ClipController:
    """One frozen frame, many named areas, one explicit export worker."""

    def __init__(self, viewer: Viewer, *, source_path=None, output_text_clip=None,
                 output_ansi_clip=None, output_png_clip=None, output_geojson_clip=None,
                 clipboard="auto", clip_source="auto", clip_overwrite=True) -> None:
        if source_path is None and viewer.navigation is not None:
            candidate = viewer.navigation.document.path
            source_path = (candidate if remote_scheme(candidate) is None and
                           Path(candidate).is_file() else None)
        clip_options(source_path=source_path, output_text_clip=output_text_clip,
                     output_ansi_clip=output_ansi_clip, output_png_clip=output_png_clip,
                     output_geojson_clip=output_geojson_clip, clipboard=clipboard,
                     clip_source=clip_source, clip_overwrite=clip_overwrite)
        self.viewer = viewer
        # These stay internal, for extraction and overwrite protection only.
        self.source = None if source_path is None else Path(source_path).resolve()
        self.source_stamp = None if self.source is None else file_stamp(self.source)
        self.paths = {key: None if value is None else Path(value).expanduser() for key, value in
                      ((False, output_text_clip), (True, output_ansi_clip),
                       ("png", output_png_clip), ("geojson", output_geojson_clip))}
        self.clipboard, self.clip_source, self.overwrite = clipboard, clip_source, clip_overwrite
        self.selection: SelectionSet | None = None
        self.viewport = self.raster_shape = self.pdf_page = None
        self.identities = IdentityFactory()
        self.original_frame = None
        self.preview_modes = None
        self.preview_frames = {}
        self.ascii_preview = False
        self._executor: ThreadPoolExecutor | None = None
        self._task: asyncio.Task | None = None
        self._closed = False
        self.pressed_button = None

    @property
    def geojson_name(self):
        return None if self.selection is None else self.selection.active.identity.name

    @geojson_name.setter
    def geojson_name(self, value):
        if self.selection is not None:
            self.selection.rename(value)

    @property
    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def source_label(self) -> str:
        if self.pdf_page is not None and not self.ascii_preview and self.selection is not None:
            shapes = [a.shape for a in self.selection.areas if not a.shape.empty]
            if len(shapes) <= 1 and all(s.kind == "rectangle" for s in shapes):
                return "PDF text"
        return self.preview_modes.label if self.ascii_preview else "screen text"

    def notify(self, message: str) -> None:
        self.viewer.message = message
        if self.viewer.application is not None:
            self.viewer.application.invalidate()

    def start(self, kind: str = "rectangle") -> None:
        viewer, nav = self.viewer, self.viewer.navigation
        if viewer.histogram_mode:
            self.notify("Return to image view with H before selecting an image region.")
            return
        if (self._closed or viewer.editing is not None or viewer.frame is None or viewer.busy
                or viewer.frame.shape != (viewer.canvas_size[1], viewer.canvas_size[0])
                or viewer.displayed_generation != viewer.generation
                or (nav is not None and (
                    nav.pending is not None or nav.target != nav.active.index
                ))):
            self.notify("Wait for the current frame before selecting.")
            return
        view = viewer.viewport
        rows, columns = viewer.frame.shape
        height, width = viewer.session.info.shape
        image_bounds = ((0 - view.x) / view.width * columns, (0 - view.y) / view.height * rows,
                        (width - view.x) / view.width * columns,
                        (height - view.y) / view.height * rows)
        try:
            selection = SelectionSet(viewer.frame, viewer.cell_lines, kind, self.identities,
                                     image_bounds=image_bounds)
        except (ValueError, RuntimeError) as error:
            self.notify(str(error))
            return
        self.selection = selection
        self.viewport, self.raster_shape = view, viewer.session.info.shape
        self.pdf_page = (nav.active.index if nav is not None and nav.document.kind == "pdf"
                         and self.clip_source == "auto" else None)
        self.original_frame = viewer.frame
        self.preview_modes = viewer.mode_navigation.clone()
        self.preview_frames = {}
        self.ascii_preview = self.preview_modes.family == "ascii"
        viewer.canvas._drag = None
        viewer.application.layout.focus(viewer.canvas)
        self.notify("Click first point / Enter: close | a: add area" if kind == "polygon" else
                    "Drag a box | Space: anchor | a: add area")

    def toggle(self, kind: str = "rectangle") -> None:
        if self.viewer.histogram_mode:
            self.notify("Return to image view with H before selecting an image region.")
            return
        if self.selection is None:
            self.start(kind)
        elif self.selection.kind == kind:
            self.end()
        else:
            self.add_area(kind)

    def start_polygon(self) -> None:
        if self.viewer.histogram_mode:
            self.notify("Return to image view with H before selecting an image region.")
            return
        self.toggle("polygon")

    def add_area(self, kind: str | None = None) -> None:
        if self.selection is None:
            return
        try:
            self.selection.add(kind)
        except (ValueError, RuntimeError) as error:
            self.notify(str(error))
            return
        self.notify("New area | s/v: switch/exit | [/]: area | Del: remove")

    def cycle_area(self, delta: int) -> None:
        if self.selection is not None:
            self.selection.cycle(delta)
            self.notify("n: rename active area | all areas are exported")

    def remove_area(self) -> None:
        if self.selection is not None:
            try:
                self.selection.remove()
            except RuntimeError as error:
                self.notify(str(error))
                return
            self.notify("Area removed.")

    def end(self, *, message="Selection closed; navigation resumed.", resume=True) -> None:
        if self.selection is None:
            return
        self.selection = None
        self.viewport = self.raster_shape = self.pdf_page = None
        self.original_frame = None
        self.preview_modes = None
        self.preview_frames = {}
        self.ascii_preview = False
        self.viewer.canvas._drag = None
        if self.viewer.editing in CLIP_EDIT_STATES:
            self.viewer.cancel_edit()
        self.notify(message)
        if resume:
            self.viewer.request_frame()

    def move(self, dx: int, dy: int, *, extend=False) -> None:
        if self.selection is not None:
            try:
                self.selection.move(dx, dy, extend=extend)
            except ValueError as error:
                self.notify(str(error))
            self.viewer.application.invalidate()

    def mark(self) -> None:
        if self.selection is None:
            return
        try:
            self.selection.mark()
        except ValueError as error:
            self.notify(str(error))
            return
        self.notify("Closed | Tab: reopen | a: add area" if self.selection.closed else
                    "Click first point / Enter: close" if self.selection.kind == "polygon" else
                    "Arrows: resize | Tab: swap corners | a: add area")

    def enter(self) -> None:
        if (self.selection is not None and self.selection.kind == "polygon"
                and not self.selection.closed):
            try:
                self.selection.finish()
            except ValueError as error:
                self.notify(str(error))
                return
            self.notify("Closed | y: text | i: PNG | j: GeoJSON | a: add area")
        else:
            self.submit()

    def swap_corner(self) -> None:
        if self.selection is not None:
            self.selection.swap_corner()
            self.notify("Tab: reopen / undo point" if self.selection.kind == "polygon"
                        else "Corner swapped.")

    def edge(self, *, end=False, extend=False) -> None:
        if self.selection is not None:
            x, y = self.selection.cursor
            target = ((self.selection.frame.shape[1] - 1, self.selection.frame.shape[0] - 1)
                      if end else (0, 0))
            self.move(target[0] - x, target[1] - y, extend=extend)

    def cycle_preview(self, family: str) -> None:
        """m/M: cycle frozen artwork/ASCII without reading the image again.

        Only the glyphs change, not cell positions, selected area identities, or
        the browsing renderer. A finer style may upscale the cached sample grid.
        """
        if self.selection is None or self.preview_modes is None:
            return
        candidate = self.preview_modes.clone()
        if family == "color":
            candidate.advance_color()
        elif family == "ascii":
            candidate.advance_ascii()
        else:
            raise ValueError("Preview family must be color or ascii")
        viewer = self.viewer
        renderer = candidate.make_renderer(viewer.renderer)
        key = (renderer.mode, renderer.color, renderer.ramp,
               renderer.invert, renderer.cell_aspect)
        original = viewer.renderer
        try:
            if key == (original.mode, original.color, original.ramp,
                       original.invert, original.cell_aspect):
                frame = self.original_frame
            elif key in self.preview_frames:
                frame = self.preview_frames[key]
            else:
                if viewer.samples is None:
                    raise ValueError("No cached preview is available for this style")
                styles = viewer.session.prepare_styles(
                    viewer.samples, windows=[viewer.windows[i]
                                             for i in viewer.samples.plan.channels])
                styles = apply_channel_colors(styles, viewer.samples.plan.channels,
                                              viewer.channel_colors)
                frame = viewer.session.render(
                    viewer.samples, styles=styles, renderer=renderer,
                    rows=self.selection.frame.shape[0], columns=self.selection.frame.shape[1])
                self.preview_frames[key] = frame
            self.selection.set_frame(frame)
        except (ValueError, RuntimeError) as error:
            self.notify(str(error))
            return
        self.preview_modes = candidate
        self.ascii_preview = candidate.family == "ascii"
        hint = "M: next | m: art" if self.ascii_preview else "m: next | M: ASCII"
        self.notify(f"{candidate.label} | {hint}")

    def _areas(self):
        if self.selection is None:
            self.notify("Create a selection first.")
            return None
        try:
            return self.selection.snapshots()
        except ValueError as error:
            self.notify(str(error))
            return None

    def save(self, *, ansi=False, image=False, geojson=False) -> None:
        if self._closed or self.busy:
            self.notify("A clip is already being prepared.")
            return
        if self._areas() is None:
            return
        key = "geojson" if geojson else "png" if image else ansi
        if self.paths[key] is not None:
            self._submit(key, copy=False, path=self.paths[key])
            return
        viewer = self.viewer
        viewer.editing = {False: "save-text", True: "save-ansi", "png": "save-png",
                          "geojson": "save-geojson"}[key]
        # Never derive a suggested filename from source metadata or a user label.
        viewer.entry.text = {False: "selection.txt", True: "selection.ansi",
                             "png": "selection.png", "geojson": "regions.geojson"}[key]
        viewer.entry.buffer.cursor_position = len(viewer.entry.text)
        viewer.application.layout.focus(viewer.entry)
        viewer.application.invalidate()

    def begin_name(self) -> None:
        if self.selection is None:
            return
        self.viewer.editing = "geojson-name"
        self.viewer.entry.text = self.geojson_name
        self.viewer.entry.buffer.cursor_position = len(self.viewer.entry.text)
        self.viewer.application.layout.focus(self.viewer.entry)
        self.viewer.application.invalidate()

    def accept_name(self, text: str) -> bool:
        if self.selection is None:
            return False
        try:
            self.selection.rename(text)
        except ValueError as error:
            self.notify(str(error))
            return False
        self.viewer.cancel_edit()
        self.notify("Name updated.")
        return True

    def accept_path(self, text: str, *, ansi=False, image=False, geojson=False) -> bool:
        key = "geojson" if geojson else "png" if image else ansi
        try:
            if not text.strip():
                raise ValueError("Enter a file path")
            path = Path(text).expanduser()
            paths = {**self.paths, key: path}
            clip_options(source_path=self.source, clip_overwrite=self.overwrite,
                         output_text_clip=paths[False], output_ansi_clip=paths[True],
                         output_png_clip=paths["png"], output_geojson_clip=paths["geojson"])
        except (ValueError, OSError) as error:
            self.notify(f"Cannot save: {error}")
            return False
        self.paths[key] = path
        self.viewer.cancel_edit()
        self._submit(key, copy=False, path=path)
        return True

    def submit(self, *, ansi=False, copy=True, path=None) -> None:
        self._submit(ansi, copy=copy, path=path)

    def submit_image(self, *, copy=True, path=None) -> None:
        self._submit("png", copy=copy, path=path)

    def submit_geojson(self, *, copy=True, path=None) -> None:
        self._submit("geojson", copy=copy, path=path)

    def _submit(self, key, *, copy=True, path=None) -> None:
        if self._closed or self.busy:
            self.notify("A clip is already being prepared.")
            return
        areas = self._areas()
        if areas is None:
            return
        if path is None and copy:
            path = self.paths[key]
        if copy and self.clipboard == "off" and path is None:
            self.save(ansi=key is True, image=key == "png", geojson=key == "geojson")
            return
        # Capture immutable geometry, identities, frame and settings before dispatch.
        selection = self.selection
        geometries = tuple(area.geometry for area in areas)
        y0, y1, x0, x1 = union_bounds(geometries)
        frame = selection.frame.crop(y0, y1, x0, x1)
        text_frame = selection.clip() if key in (False, True) else None
        view, raster_shape, frame_shape = self.viewport, self.raster_shape, selection.frame.shape
        image_bounds, source, stamp = selection.image_bounds, self.source, self.source_stamp
        clipboard, overwrite = self.clipboard, self.overwrite
        cell_height = round(12 * self.viewer.renderer.cell_aspect)
        page = self.pdf_page if key is False and self.source_label == "PDF text" else None
        label = ("PNG" if key == "png" else "GeoJSON" if key == "geojson" else
                 "PDF text" if page is not None else "ASCII" if self.ascii_preview else
                 "screen text" if key is False else "ANSI artwork")

        def prepare() -> ClipResult:
            try:
                if key == "geojson":
                    content = dump_geojson([
                        geometry_feature(a.geometry, viewport=view, frame_shape=frame_shape,
                                         raster_shape=raster_shape, identity=a.identity)
                        for a in areas])
                elif key == "png":
                    # Do not use the cell-masked frame: polygon PNG edges are subcell.
                    content = render_clip_png(frame, cell_height=cell_height, regions=geometries,
                                              origin=(x0, y0), image_bounds=image_bounds)
                elif page is not None:
                    if stamp is not None and file_stamp(source) != stamp:
                        raise ValueError("Input changed on disk; reopen it before copying PDF text")
                    rows, columns = frame_shape
                    bounds = (view.x + x0 / columns * view.width, view.y + y0 / rows * view.height,
                              view.x + x1 / columns * view.width, view.y + y1 / rows * view.height)
                    content = extract_pdf_text(
                        source, page, bounds=bounds, raster_shape=raster_shape
                    )
                    if not content.strip():
                        raise ValueError("No embedded PDF text in this box. No OCR was run; "
                                         "t/T exports terminal artwork instead.")
                else:
                    content = text_frame.to_text(ansi=key is True)
                messages = []
                if path is not None:
                    write = write_png_clip if key == "png" else write_text_clip
                    write(path, content, source=source, overwrite=overwrite)
                    messages.append(f"Saved {label}: {path}")
                delivery = None
                if copy and clipboard != "off":
                    try:
                        deliver = clipboard_png if key == "png" else clipboard_delivery
                        delivery = deliver(content, clipboard)
                        messages.append(f"{delivery.message} ({label})")
                    except (ValueError, OSError, RuntimeError) as error:
                        messages.append(f"Clipboard unavailable: {error}")
                return ClipResult(" | ".join(messages), delivery)
            except Exception as error:
                return ClipResult(f"{label} clip failed: {error}")

        if self._executor is None:
            self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="twhy-clip")
        future = asyncio.get_running_loop().run_in_executor(self._executor, prepare)

        async def deliver() -> None:
            result = await asyncio.shield(future)
            if self._closed or not self.viewer.application.is_running:
                return
            if result.delivery is not None and result.delivery.sequence:
                try:
                    self.viewer.application.output.write_raw(result.delivery.sequence)
                    self.viewer.application.output.flush()
                except (OSError, NotImplementedError) as error:
                    self.notify(f"{result.message} | Terminal write failed: {error}")
                    return
            self.notify(result.message)

        self._task = self.viewer.application.create_background_task(deliver())
        self.notify(f"Preparing {label}...")

    def status(self) -> str:
        if self.selection is None:
            return ""
        s = self.selection
        state = "closed" if s.closed else "open"
        tool = "RECT" if s.kind == "rectangle" else f"POLY {state}"
        return (f"{tool} {s.active_index+1}/{len(s.areas)} | "
                f"Name: {s.active.identity.name} (n to rename) | {self.source_label}")

    def close(self) -> None:
        self._closed = True
        self.selection = None
        self.original_frame = None
        self.preview_modes = None
        self.preview_frames.clear()
        if self._executor is not None:
            self._executor.shutdown(wait=True, cancel_futures=False)
            self._executor = None
