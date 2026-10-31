"""Public planning, sampling, and rendering stages for a borrowed open source."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from math import ceil, floor, isfinite
from numbers import Integral
from threading import RLock
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray

from ._validation import positive_integer
from .compositing import ChannelStyle, compose_channels
from .channel_colors import default_color
from .intensity_window import IntensityWindow, estimate_window
from .view_info import PyramidLevel, ReadBudgetExceeded, ViewInfo
from .resampling import resample_image
from .runtime_overview import (
    DEFAULT_OVERVIEW_CACHE_MIB, DEFAULT_OVERVIEW_MAX_SOURCE_PIXELS,
    OverviewCache, OverviewProgress,
)
from .sampled_overview import (
    SampledOverview, interpolate_overview, patch_mean, plan_sampled_overview,
)
from .text_image import TextImage
from .text_renderer import TextRenderer
from .viewport import Viewport

if TYPE_CHECKING:
    from omeify import Image


@dataclass(frozen=True, slots=True)
class ReadPlan:
    """A bounded source rectangle and its exact display sampling geometry."""

    viewport: Viewport
    level: PyramidLevel
    bounds: tuple[int, int, int, int]  # y0, y1, x0, x1 at selected level
    channels: tuple[int, ...]
    sample_shape: tuple[int, int]
    source_samples: int
    sampled_overview: SampledOverview | None = None


@dataclass(frozen=True, slots=True)
class ViewSamples:
    """Independent, read-only preview intensities, in CYX or RGB YXS order.

    Values are area-averaged raw display samples, not quantitative whole-slide
    measurements. The mask is represented by NaN rather than an extra raster.
    cached_overview identifies a completed full-coverage display reduction used
    instead of the sparse fallback described by the retained ReadPlan.
    """

    values: NDArray
    plan: ReadPlan
    is_rgb: bool
    cached_overview: bool = False

    def __post_init__(self) -> None:
        value = np.array(self.values, copy=True)
        rows, columns = self.plan.sample_shape
        expected = ((rows, columns, 3) if self.is_rgb else
                    (len(self.plan.channels), rows, columns))
        if value.shape != expected or value.dtype.kind != "f":
            raise ValueError(f"Preview values must be floating point with shape {expected}")
        value.flags.writeable = False
        object.__setattr__(self, "values", value)

    def __repr__(self) -> str:
        return (f"ViewSamples(shape={self.values.shape}, level={self.plan.level.index}, "
                f"channels={self.plan.channels}, rgb={self.is_rgb})")


class ViewSession:
    """Bounded display over one borrowed, already-open Omeify image.

    Use a context to release preview caches and the session-bound borrowed view.
    Closing the session never closes its parent image. Closing/reopening the
    parent invalidates the session, including cached previews. Optional runtime
    overviews are display-only reductions, never new source levels or files.
    Calls within the session are serialized;
    callers must not concurrently mutate or close the parent.
    """

    def __init__(
        self, image: Image, *, name: str = "Image", cache_mib: float = 32.0,
        max_read_pixels: int = 4_194_304,
        overview_cache_mib: float = DEFAULT_OVERVIEW_CACHE_MIB,
        overview_max_source_pixels: int = DEFAULT_OVERVIEW_MAX_SOURCE_PIXELS,
    ) -> None:
        from omeify import Image

        if not isinstance(image, Image):
            raise TypeError("ViewSession requires an Omeify Image")
        if not image.is_open:
            raise RuntimeError("ViewSession requires an open image")
        if image.image_type == "label":
            raise ValueError(
                "Categorical label coloring is not supported; do not window object IDs"
            )
        if not isinstance(name, str) or not name.strip():
            raise ValueError("name must be a nonempty display label")
        if not isfinite(cache_mib) or cache_mib < 0:
            raise ValueError("cache_mib must be finite and nonnegative")
        self.max_read_pixels = positive_integer(max_read_pixels, "max_read_pixels")
        self._info = ViewInfo.from_image(image, name=name)
        self._overviews = OverviewCache(cache_mib=overview_cache_mib,
                                        max_source_pixels=overview_max_source_pixels)
        # A public Omeify view pins the original session without private epochs
        # or zero-pixel reads merely to check lifetime.
        self._image = image.with_metadata().open()
        self._budget = int(cache_mib * 1024 * 1024)
        self._cache: OrderedDict[ReadPlan, ViewSamples] = OrderedDict()
        self._cache_bytes = 0
        self._lock = RLock()
        self._context_active = False

    @property
    def info(self) -> ViewInfo:
        return self._info

    @property
    def is_open(self) -> bool:
        return self._image.is_open

    def _require_image_open(self) -> None:
        if not self.is_open:
            raise RuntimeError("The session's image lifetime has ended; create a new ViewSession")

    def _select_channels(self, channels: Sequence[int]) -> tuple[int, ...]:
        if len(channels) == 0:
            raise ValueError("Select at least one channel")
        result = []
        for index in channels:
            if isinstance(index, (bool, np.bool_)) or not isinstance(index, Integral):
                raise TypeError("Channel indices must be integers")
            if not 0 <= index < len(self.info.channels):
                raise IndexError(f"Channel {index} is outside 0..{len(self.info.channels) - 1}")
            if index in result:
                raise ValueError(f"Channel {index} is selected more than once")
            result.append(int(index))
        return tuple(result)

    @property
    def cache_bytes(self) -> int:
        return self._cache_bytes

    @property
    def overview_cache_bytes(self) -> int:
        """Retained plus in-progress overview arrays, separate from preview bytes."""
        return self._overviews.nbytes

    @property
    def overview_status(self) -> str:
        return self._overviews.status

    def overview_ready(self, channels: Sequence[int] = (0,)) -> bool:
        """Whether all selected channels have a complete cached reduction; no I/O."""
        with self._lock:
            self._require_image_open()
            selected = self._select_channels(channels)
            return self._overviews.get(self.info, selected, self.max_read_pixels) is not None

    def quick_overview_eligible(self, channels: Sequence[int] = (0,)) -> bool:
        """Whether a complete startup scan fits the configured work/RAM limits.

        Its *duration* is governed by startup_overview_seconds, not another fixed
        source-size cutoff. A fast, moderately large coarse level should get its
        chance to finish before the first frame instead of always flashing sparse.
        """
        with self._lock:
            self._require_image_open()
            selected = self._select_channels(channels)
            spec, _ = self._overviews.spec(self.info, selected, self.max_read_pixels)
            return spec is not None

    def step_overview(self, channels: Sequence[int] = (0,)) -> OverviewProgress:
        """Prepare at most one native chunk of an optional whole-image display cache.

        Each chunk is <= max_read_pixels and <=262,144 source samples. The total
        scan has its own overview_max_source_pixels cap. Calling this method is
        explicit extra I/O; normal plan/sample/fit never starts a build. Callers
        may interleave foreground work or cancel between steps. Never call from
        the UI thread: native reads cannot be forcibly interrupted safely.
        """
        with self._lock:
            self._require_image_open()
            selected = self._select_channels(channels)

            def read(channel, level, bounds):
                return self._image[channel].read_region(*bounds, level=level)

            progress = self._overviews.step(self.info, selected, self.max_read_pixels, read)
            if progress.published:
                # Existing ViewSamples (including frozen selections) remain valid,
                # but an old sparse preview must not hide a completed reduction.
                for plan in tuple(self._cache):
                    if plan.sampled_overview is not None:
                        self._cache_bytes -= self._cache.pop(plan).values.nbytes
            return progress

    def cancel_overview(self) -> None:
        """Discard unfinished work, retaining completed cache entries. No I/O."""
        with self._lock:
            self._overviews.cancel()

    def clear_cache(self) -> None:
        """Release preview/overview arrays, not the borrowed image or decoder cache."""
        with self._lock:
            self._cache.clear()
            self._cache_bytes = 0
            self._overviews.clear()

    def close(self) -> None:
        """End this view and release its previews; the parent remains caller-owned."""
        with self._lock:
            self.clear_cache()
            self._image.close()

    def __enter__(self) -> ViewSession:
        self._require_image_open()
        if self._context_active:
            raise RuntimeError("Nested contexts on one ViewSession are not supported")
        self._context_active = True
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self._context_active = False
        self.close()

    def plan(
        self,
        viewport: Viewport,
        *,
        rows: int,
        columns: int,
        channels: Sequence[int] = (0,),
        allow_sampled_overview: bool = False,
    ) -> ReadPlan:
        """Choose a stored pyramid level and reject excessive reads before I/O.

        rows/columns describe the sample raster from renderer.sample_shape(),
        not necessarily the terminal cell grid. Declared scales are authoritative.
        Unknown-scale levels use labelled approximate extent-fit display mapping.
        An explicitly allowed sampled overview makes bounded patch reads when even
        the coarsest native level exceeds the source-read budget. Its interpolated
        output is approximate, never an exact integrated source overview.
        """
        self._require_image_open()
        rows, columns = positive_integer(rows, "rows"), positive_integer(columns, "columns")
        selected = self._select_channels(channels)
        candidates = [level for level in self.info.levels
                      if level.scale_x <= viewport.width / columns
                      and level.scale_y <= viewport.height / rows]
        level = max(candidates, key=lambda x: x.scale_x * x.scale_y,
                    default=self.info.levels[0])
        x0 = min(level.width, max(0, floor(viewport.x / level.scale_x)))
        y0 = min(level.height, max(0, floor(viewport.y / level.scale_y)))
        x1 = min(level.width, max(0, ceil((viewport.x + viewport.width) / level.scale_x)))
        y1 = min(level.height, max(0, ceil((viewport.y + viewport.height) / level.scale_y)))
        count = max(0, x1 - x0) * max(0, y1 - y0) * len(selected)
        count *= 3 if self.info.is_rgb else 1
        overview = None
        if count > self.max_read_pixels and allow_sampled_overview:
            # Prefer a full native region at lower detail before using sparse
            # sampling. Runtime reductions can replace the sparse plan at sample().
            level = max(self.info.levels, key=lambda item: item.scale_x * item.scale_y)
            x0 = min(level.width, max(0, floor(viewport.x / level.scale_x)))
            y0 = min(level.height, max(0, floor(viewport.y / level.scale_y)))
            x1 = min(level.width, max(0, ceil((viewport.x + viewport.width) / level.scale_x)))
            y1 = min(level.height, max(0, ceil((viewport.y + viewport.height) / level.scale_y)))
            components = len(selected) * (3 if self.info.is_rgb else 1)
            count = max(0, x1 - x0) * max(0, y1 - y0) * components
            if count > self.max_read_pixels and self.max_read_pixels >= components:
                overview = plan_sampled_overview(
                    viewport, shape=self.info.shape, level=level, rows=rows, columns=columns,
                    pixel_budget=self.max_read_pixels // components,
                )
                count = overview.pixels_per_channel * components
        if count > self.max_read_pixels:
            raise ReadBudgetExceeded(
                f"Viewport needs {count:,} source samples at level {level.index}; "
                f"budget is {self.max_read_pixels:,}. Zoom in or supply a coarser pyramid."
            )
        return ReadPlan(viewport, level, (y0, y1, x0, x1), selected, (rows, columns),
                        count, overview)

    def fit(
        self,
        *,
        columns: int,
        rows: int,
        renderer: TextRenderer,
        channels: Sequence[int] = (0,),
    ) -> tuple[Viewport, bool]:
        """Return an image-fit viewport, or an explicitly flagged bounded center crop.

        A large file without a sufficiently coarse pyramid cannot have a cheap
        faithful overview. The boolean reports whether the read budget limited
        the fit. No conversion, sparse fake overview, or full-slide scan occurs.
        """
        self._require_image_open()
        viewport = Viewport.fit(self.info.shape, columns=columns, rows=rows,
                               cell_aspect=renderer.cell_aspect,
                               pixel_aspect=self.info.pixel_aspect)
        sample_rows, sample_columns = renderer.sample_shape(columns=columns, rows=rows)
        limited = False
        for _ in range(128):
            try:
                self.plan(viewport, rows=sample_rows, columns=sample_columns, channels=channels)
                return viewport, limited
            except ReadBudgetExceeded:
                viewport, limited = viewport.zoom(1.5), True
        raise ReadBudgetExceeded("Read budget is too small even for the minimum viewport")

    def sample(self, plan: ReadPlan) -> ViewSamples:
        """Execute a plan using regional Omeify reads and finite-value area averaging."""
        with self._lock:
            # Revalidate a public record; do not allow a constructed plan to
            # bypass budget, source, level, or channel validation.
            expected = self.plan(plan.viewport, rows=plan.sample_shape[0],
                                 columns=plan.sample_shape[1], channels=plan.channels,
                                 allow_sampled_overview=True)
            if plan != expected:
                raise ValueError("ReadPlan does not match this source and sampling geometry")
            if plan in self._cache:
                self._cache.move_to_end(plan)
                return self._cache[plan]
            y0, y1, x0, x1 = plan.bounds
            rows, columns = plan.sample_shape
            planes = []
            overview = plan.sampled_overview
            cached = (None if overview is None else
                      self._overviews.get(self.info, plan.channels, self.max_read_pixels))
            for position, channel in enumerate(plan.channels):
                if x0 >= x1 or y0 >= y1:
                    shape = ((rows, columns, 3) if self.info.is_rgb else (rows, columns))
                    preview = np.full(shape, np.nan, dtype=np.float64)
                elif cached is not None:
                    preview = cached[position].sample(plan.viewport, rows=rows, columns=columns)
                else:
                    if overview is not None:
                        # Each native region is small. Sum of all such reads,
                        # including every RGB sample/selected channel, is <=budget.
                        readings = [patch_mean(self._image[channel].read_region(
                            *region, level=plan.level.index)) for region in overview.regions]
                        tail = (3,) if self.info.is_rgb else ()
                        grid = np.asarray(readings, dtype=np.float64).reshape(
                            (*overview.grid_shape, *tail))
                        preview = interpolate_overview(
                            grid, overview, viewport=plan.viewport, shape=self.info.shape,
                            rows=rows, columns=columns)
                    else:
                        pixels = self._image[channel].read_region(
                            y0, y1, x0, x1, level=plan.level.index,
                        )
                        viewport, level = plan.viewport, plan.level
                        preview = resample_image(
                            pixels, rows=rows, columns=columns,
                            bounds=(viewport.x / level.scale_x - x0,
                                    viewport.y / level.scale_y - y0,
                                    viewport.width / level.scale_x,
                                    viewport.height / level.scale_y),
                            coverage_shape=(
                                min(y1 - y0, self.info.shape[0] / level.scale_y - y0),
                                min(x1 - x0, self.info.shape[1] / level.scale_x - x0),
                            ),
                        )
                planes.append(preview)
            values = planes[0] if self.info.is_rgb else np.stack(planes)
            samples = ViewSamples(
                values, plan, self.info.is_rgb, cached_overview=cached is not None
            )
            size = samples.values.nbytes
            if size <= self._budget:
                while self._cache and self._cache_bytes + size > self._budget:
                    self._cache_bytes -= self._cache.popitem(last=False)[1].values.nbytes
                self._cache[plan] = samples
                self._cache_bytes += size
            return samples

    def prepare_styles(
        self,
        samples: ViewSamples,
        *,
        windows: Sequence[IntensityWindow | None] | None = None,
    ) -> tuple[ChannelStyle, ...]:
        """Resolve explicit windows or estimate initial display windows from a preview.

        windows follows the sampled channel order, not the full source channel
        order. Unsigned RGB defaults to its dtype range, preserving shared RGB
        balance. Other channels use finite preview percentiles. An entirely
        missing field receives a 0..1 display placeholder, not an inferred range.
        The caller may retain returned windows to keep contrast fixed while panning.
        """
        self._require_image_open()
        if windows is not None and len(windows) != len(samples.plan.channels):
            raise ValueError("One window is required for each sampled logical channel")
        styles = []
        for position, index in enumerate(samples.plan.channels):
            window = None if windows is None else windows[position]
            values = samples.values if samples.is_rgb else samples.values[position]
            if window is None:
                if samples.is_rgb and self.info.dtype.kind in "bu":
                    maximum = (1 if self.info.dtype.kind == "b" else
                               np.iinfo(self.info.dtype).max)
                    window = IntensityWindow(0, float(maximum))
                elif np.isfinite(values).any():
                    window = estimate_window(values)
                else:
                    window = IntensityWindow(0, 1)
            color = default_color(index, len(self.info.channels), is_rgb=samples.is_rgb)
            styles.append(ChannelStyle(window, color))
        return tuple(styles)

    def render(
        self,
        samples: ViewSamples,
        *,
        styles: Sequence[ChannelStyle],
        renderer: TextRenderer,
        columns: int,
        rows: int,
    ) -> TextImage:
        """Compose independently windowed samples and render terminal cells.

        RGB uses one logical style and applies its window equally to all three
        RGB samples; its pseudocolor field is not used. Monochrome multi-marker
        output uses the peak composed signal rather than a color-weighted loss.
        """
        self._require_image_open()
        if len(styles) != len(samples.plan.channels):
            raise ValueError("One style is required for each sampled logical channel")
        if samples.is_rgb:
            if tuple(styles[0].color) != (1.0, 1.0, 1.0):
                raise ValueError("RGB samples require a white style; RGB is not pseudocolored")
            normalized = styles[0].window.apply(samples.values)
        else:
            normalized = compose_channels(samples.values, styles)
        if not renderer.color:
            normalized = np.max(normalized, axis=-1)
        return renderer.render(normalized, columns=columns, rows=rows)

    def __repr__(self) -> str:
        return (f"ViewSession(name={self.info.name!r}, is_open={self.is_open}, "
                f"preview_cache_mib={self.cache_bytes / 1024**2:.2f})")
