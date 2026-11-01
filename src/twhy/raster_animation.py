"""Bounded, lazy GIF frame preparation for the interactive document navigator.

Pillow owns GIF disposal, transparency, palettes and frame compositing. twhy owns
only the RGB display pyramid and a byte-counted cache of immutable frame arrays.
No frame is read to discover animation count, and no complete animation is loaded.
"""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from threading import RLock

import numpy as np

from .image_pyramid import image_pyramid


DEFAULT_GIF_CACHE_MIB = 64
DEFAULT_GIF_DURATION = 0.1
MIN_GIF_DURATION = 0.04  # A 0-ms GIF delay cannot be represented as instantaneous playback.


def is_gif(path: Path) -> bool:
    """Recognize actual GIF bytes, independently of filename suffix."""
    with path.open("rb") as stream:
        return stream.read(6) in (b"GIF87a", b"GIF89a")


class GIFAnimation:
    """One open Pillow decoder, with a bounded LRU of prepared display pyramids.

    Call ``arrays`` from the document's single source-loader thread. Cached arrays
    are immutable and safe to borrow after eviction. The active Image and native
    Pillow scratch are not counted against the retained-array cache budget.
    """

    def __init__(self, path, *, background=(255, 255, 255), cache_mib=DEFAULT_GIF_CACHE_MIB):
        from PIL import Image

        self._image = Image.open(path, formats=["GIF"])
        self.count = int(getattr(self._image, "n_frames", 1))
        self.background = tuple(background)
        self.limit = int(cache_mib * 1024**2)
        self._cache: OrderedDict[int, tuple[np.ndarray, ...]] = OrderedDict()
        self._bytes = 0
        self.can_prefetch = self.limit > 0
        self._durations: dict[int, float] = {}
        self._lock = RLock()
        self._closed = False

    @property
    def cached_frames(self) -> tuple[int, ...]:
        with self._lock:
            return tuple(self._cache)

    @property
    def cached_bytes(self) -> int:
        with self._lock:
            return self._bytes

    def duration(self, frame: int) -> float:
        """GIF frame delay in seconds, with a humane minimum for zero-delay GIFs."""
        # Never block the UI while the source-loader thread decodes another frame.
        # The only writer runs in that loader, and replacing one dict entry is atomic.
        return self._durations.get(frame, DEFAULT_GIF_DURATION)

    def arrays(self, frame: int) -> tuple[np.ndarray, ...]:
        with self._lock:
            if self._closed:
                raise RuntimeError("GIF decoder is closed")
            if not 0 <= frame < self.count:
                raise IndexError(f"Frame {frame} does not exist; choose 0..{self.count - 1}")
            cached = self._cache.get(frame)
            if cached is not None:
                self._cache.move_to_end(frame)
                return cached
            # Pillow seek/load applies disposal and composes the logical frame.
            # Reopening for each frame would discard both decoder state and this cache.
            self._image.seek(frame)
            self._image.load()
            duration_ms = self._image.info.get("duration", 100)
            try:
                duration = float(duration_ms) / 1000
            except (TypeError, ValueError):
                duration = DEFAULT_GIF_DURATION
            self._durations[frame] = (max(MIN_GIF_DURATION, duration)
                                      if np.isfinite(duration) else DEFAULT_GIF_DURATION)
            from PIL import Image
            with self._image.convert("RGBA") as rgba, Image.new(
                "RGBA", self._image.size, (*self.background, 255),
            ) as matte:
                matte.alpha_composite(rgba)
                with matte.convert("RGB") as rgb:
                    pixels = np.array(rgb, dtype=np.uint8, copy=True)
            levels = image_pyramid(pixels)
            size = sum(array.nbytes for array in levels)
            if size > self.limit:
                # Every GIF frame has the same dimensions and thus approximately
                # the same pyramid cost. Avoid speculative work that cannot stick.
                self.can_prefetch = False
            if size <= self.limit:
                while self._cache and self._bytes + size > self.limit:
                    _, removed = self._cache.popitem(last=False)
                    self._bytes -= sum(array.nbytes for array in removed)
                self._cache[frame] = levels
                self._bytes += size
            return levels

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                self._cache.clear()
                self._bytes = 0
                self._image.close()
