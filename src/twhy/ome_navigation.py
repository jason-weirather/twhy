"""OME source lifetimes and initial-plane selection for the file frontend.

Omeify alone interprets axes, pyramids and storage. This module owns no decoder
or raw-pixel cache. Its reference-counted handle keeps one open dataset alive
while old/new immutable plane Images overlap during a render handoff.
"""
from __future__ import annotations

from threading import RLock
from typing import TYPE_CHECKING

from .source_input import remote_scheme, s3_options

if TYPE_CHECKING:
    from omeify import Image, ImageDataset


def dataset_options(path, kind, *, series=0, group="", s3_endpoint_url=None,
                    s3_anonymous=False) -> dict:
    options = {"input_type": "ome_zarr" if kind == "zarr" else "ome_tiff",
               "series": series}
    if kind == "zarr":
        options["group"] = group
        options["storage_options"] = (s3_options(s3_endpoint_url, anonymous=s3_anonymous)
                                      if remote_scheme(path) == "s3" else None)
    return options


def open_ome_dataset(path, kind, **options) -> ImageDataset:
    """Construct the real dataset, with an actionable error for an older checkout."""
    import omeify
    open_dataset = getattr(omeify, "open_dataset", None)
    if open_dataset is None:
        raise RuntimeError(
            "Z/T navigation requires Omeify's ImageDataset API. Install the updated "
            "Omeify z_t_support checkout (74bf991 or later) in this Python environment."
        )
    return open_dataset(path, **dataset_options(path, kind, **options))


def initial_plane(dataset: ImageDataset, *, z_index=None, t_index=None) -> Image:
    """twhy starts at middle Z and T=0; absent axes stay absent.

    Explicit values, including indices on absent axes, are validated by Omeify.
    This frontend default does not relax Omeify's explicit-selection contract.
    """
    depth = dataset.axis_info("Z")
    z = depth.size // 2 if z_index is None and depth is not None else z_index
    t = 0 if t_index is None and dataset.axis_info("T") is not None else t_index
    return dataset.plane(z=z, t=t)


class DatasetHandle:
    """One authoritative dataset plus references held by document/plane items.

    Loads run on one loader thread; final item releases run on the UI thread
    after render work has joined. Protect just reference accounting here, not
    storage reads: Omeify owns its own source synchronization.
    """

    def __init__(self, path, kind, **options):
        self.dataset = open_ome_dataset(path, kind, **options).open()
        self.index = options.get("series", 0)
        self._lock = RLock()
        self._references = 1

    def retain(self):
        with self._lock:
            if self._references < 1:
                raise RuntimeError("Dataset handle has been released")
            self._references += 1
        return self

    def release(self):
        with self._lock:
            if self._references < 1:
                raise RuntimeError("Dataset handle released twice")
            self._references -= 1
            if not self._references:
                self.dataset.close()


def series_count(path, kind, **options) -> int:
    """Use public Omeify inspection once, never parse OME/NGFF in twhy.

    ImageDataset currently lacks series_names. This metadata-only discovery is
    separate from the persistent pixel session and is NOT repeated on Z/T steps.
    When Omeify exposes collection descriptors directly it can replace this call.
    """
    if kind == "zarr":
        from omeify import ZarrInspector
        kwargs = dataset_options(path, kind, **options)
        kwargs.pop("input_type")
        return len(ZarrInspector(path, detail=0, **kwargs).report["series"])
    from omeify import TiffInspector
    return TiffInspector(path, detail=0).report["file"]["series_count"]
