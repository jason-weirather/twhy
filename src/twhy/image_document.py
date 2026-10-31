"""Document selection and explicit ownership, above the unchanged Omeify Image API."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING

import numpy as np

from .image_input import _background, _index, array_image, image_kind, open_image, pdf_page_count
from .ome_navigation import DatasetHandle, initial_plane, series_count
from .pdf_workers import DEFAULT_PDF_MAX_DPI, pdf_dpi_steps
from .source_input import display_name, remote_scheme

if TYPE_CHECKING:
    from omeify import Image


class DocumentItem:
    """One immutable open image, retained independently by cache and active viewer.

    Reference accounting is event-loop-owned after load() returns. Releasing the
    final reference closes the image and drops the array-owning context. An old
    image can therefore be evicted without closing it underneath an active read.
    """

    def __init__(self, stack: ExitStack, image: Image, *, index: int,
                 dpi: float | None = None, nbytes: int = 0,
                 dataset=None, handle=None) -> None:
        self.image: Image | None = image
        self.index, self.dpi, self.nbytes = index, dpi, nbytes
        self.dataset = dataset
        self._dataset_handle = handle
        selection = None if dataset is None else image.plane_selection
        self.z_index = None if selection is None else selection.z
        self.t_index = None if selection is None else selection.t
        self.axis_info = (() if dataset is None else
                          tuple(axis for name in ("Z", "T")
                                if (axis := dataset.axis_info(name)) is not None))
        self._stack = stack
        self._references = 1

    @property
    def position(self) -> tuple[int, int | None, int | None]:
        return self.index, self.z_index, self.t_index

    def retain(self) -> DocumentItem:
        if self._references < 1:
            raise RuntimeError("Document image has been released")
        self._references += 1
        return self

    def release(self) -> None:
        if self._references < 1:
            raise RuntimeError("Document image released twice")
        self._references -= 1
        if not self._references:
            try:
                self._stack.close()
            finally:
                self.image = None
                self.dataset = None
                self._dataset_handle = None


class ImageDocument:
    """Read one selected page/series; never scan pixels in the other OME series.

    load() may run in a source-loader thread. PDF refinement uses independent
    spawned processes; from_arrays() receives only completed owned RAM pyramids.
    The document does not own a renderer or introduce another image interface.
    """

    def __init__(self, path: str | Path, *, series: int = 0, page: int | None = None,
                 frame: int | None = None, pdf_max_dpi: float | None = None,
                 background=None, group: str = "", z_index: int | None = None,
                 t_index: int | None = None, s3_endpoint_url: str | None = None,
                 s3_anonymous: bool = False, input_format: str = "auto",
                 source_name: str | None = None) -> None:
        self.path = str(path) if remote_scheme(path) else Path(path).resolve()
        self.kind = image_kind(self.path, input_format=input_format)
        self.group, self.z_index, self.t_index = group, z_index, t_index
        self.s3_endpoint_url, self.s3_anonymous = s3_endpoint_url, s3_anonymous
        self.source_name = source_name or display_name(path)
        self.series = _index(series, "series")
        self.page = None if page is None else _index(page, "page", minimum=1)
        self.frame = None if frame is None else _index(frame, "frame")
        self.background = _background(background)
        self._background_option = background
        if self.kind != "pdf" and pdf_max_dpi is not None:
            raise ValueError("--pdf-max-dpi applies only to PDF")
        self.dpi_steps = pdf_dpi_steps(
            DEFAULT_PDF_MAX_DPI if pdf_max_dpi is None else pdf_max_dpi,
        ) if self.kind == "pdf" else ()
        self.initial_index = (self.page or 1) if self.kind == "pdf" else series
        self.first_index = 1 if self.kind == "pdf" else 0
        self.count = 0
        self._dataset_handle: DatasetHandle | None = None
        self._handle_lock = RLock()
        self.is_ome = (self.kind == "zarr" or
                       self.kind == "tiff" and self.path.suffix.casefold() != ".svs")
        if group and self.kind != "zarr":
            raise ValueError("--group applies only to OME-Zarr")
        if (z_index is not None or t_index is not None) and not self.is_ome:
            raise ValueError("--z-index and --t-index apply only to OME-TIFF and OME-Zarr")
        if self.is_ome and (page is not None or frame is not None or background is not None):
            raise ValueError("OME inputs use --series/--z-index/--t-index; "
                             "PDF/raster options do not apply")

    @property
    def label(self) -> str:
        return "page" if self.kind == "pdf" else "series"

    @property
    def last_index(self) -> int:
        return self.first_index + self.count - 1

    def validate_index(self, index: int) -> int:
        index = _index(index, self.label, minimum=self.first_index)
        if not self.first_index <= index <= self.last_index:
            raise ValueError(f"Choose {self.label} {self.first_index}..{self.last_index}")
        return index

    def initialize(self) -> DocumentItem:
        item = self.load(self.initial_index)
        try:
            self.count = (pdf_page_count(self.path) if self.kind == "pdf" else
                          series_count(self.path, self.kind, series=self.series, group=self.group,
                                       s3_endpoint_url=self.s3_endpoint_url,
                                       s3_anonymous=self.s3_anonymous) if self.is_ome else
                          len(item.image.series_names) if self.kind == "tiff" else 1)
            self.validate_index(self.initial_index)
            self.activate(item)
            return item
        except BaseException:
            item.release()
            self.close()
            raise

    def load(self, index: int) -> DocumentItem:
        """Open one quick preview or one region-readable OME series."""
        if self.count:
            self.validate_index(index)
        if self.is_ome:
            # Startup selectors apply only at startup; a different series starts
            # at middle Z and T=0, never with invalid old-series indices.
            return self.load_plane(index, z_index=self.z_index if not self.count else None,
                                   t_index=self.t_index if not self.count else None)
        dpi = self.dpi_steps[0] if self.kind == "pdf" else None
        stack = ExitStack()
        try:
            image = stack.enter_context(open_image(
                self.path, series=index if self.kind in {"tiff", "zarr"} else self.series,
                page=index if self.kind == "pdf" else self.page, frame=self.frame,
                pdf_dpi=dpi, background=self._background_option, group=self.group,
                z_index=self.z_index, t_index=self.t_index,
                s3_endpoint_url=self.s3_endpoint_url, s3_anonymous=self.s3_anonymous,
                input_format="zarr" if self.kind == "zarr" else "auto",
            ))
            size = (sum(int(np.prod(level.shape)) * image.dtype.itemsize for level in image.levels)
                    if self.kind == "pdf" else 0)
            return DocumentItem(stack, image, index=index, dpi=dpi, nbytes=size)
        except BaseException:
            stack.close()
            raise

    def load_plane(self, index: int, *, z_index=None, t_index=None) -> DocumentItem:
        """Select from the same session, retaining the old owner during handoff."""
        if not self.is_ome:
            raise ValueError("This document has no Z/T source")
        if self.count:
            self.validate_index(index)
        with self._handle_lock:
            previous = self._dataset_handle
            owner = previous.retain() if previous is not None and previous.index == index else None
        if owner is None:
            owner = DatasetHandle(self.path, self.kind, series=index, group=self.group,
                                  s3_endpoint_url=self.s3_endpoint_url,
                                  s3_anonymous=self.s3_anonymous)
        stack = ExitStack()
        stack.callback(owner.release)
        try:
            image = stack.enter_context(initial_plane(owner.dataset, z_index=z_index,
                                                       t_index=t_index))
            if image.image_type == "label":
                raise ValueError("Categorical label coloring is not supported; "
                                 "do not window object IDs")
            return DocumentItem(stack, image, index=index, dataset=owner.dataset, handle=owner)
        except BaseException:
            stack.close()
            raise

    def activate(self, item: DocumentItem) -> None:
        """Retain only the displayed dataset; a discarded load cannot evict it."""
        owner = item._dataset_handle
        if owner is None:
            return
        with self._handle_lock:
            previous = self._dataset_handle
            if previous is owner:
                return
            self._dataset_handle = owner.retain()
        if previous is not None:
            previous.release()

    def close(self) -> None:
        """After the loader stops, release this document's source reference.

        Any live DocumentItem keeps its own reference until its render finishes.
        """
        with self._handle_lock:
            owner, self._dataset_handle = self._dataset_handle, None
        if owner is not None:
            owner.release()

    def from_arrays(self, index: int, dpi: float, arrays) -> DocumentItem:
        stack = ExitStack()
        try:
            image = stack.enter_context(array_image(arrays))
            return DocumentItem(stack, image, index=index, dpi=dpi,
                                nbytes=sum(array.nbytes for array in arrays))
        except BaseException:
            stack.close()
            raise

    def item_name(self, item: DocumentItem) -> str:
        selection = (f"page {item.index}/{self.count} | {item.dpi:g} DPI raster"
                     if self.kind == "pdf" else
                     f"series {item.index} of {self.count} (0-based)")
        for axis in item.axis_info:
            if axis.size > 1:
                index = item.z_index if axis.name == "Z" else item.t_index
                selection += f" | {axis.name} {index}/{axis.size - 1}"
        return f"{self.source_name} | {selection}"
