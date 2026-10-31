"""Pyramid-guided defensive importance sampling of base-resolution tile clusters.

A frozen pilot chooses a proposal; independent with-replacement tile draws then
estimate a weighted base-pixel distribution. Coarse intensities never enter that
histogram. See docs/contrast-estimation.md for the estimand and equations.
"""
from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from itertools import product
from math import ceil, isqrt, prod
from time import monotonic

import numpy as np

from .contrast_statistics import ContrastConfig, ContrastEstimate, summarize_draws


@dataclass(frozen=True, slots=True)
class _Level:
    index: int
    shape: tuple[int, int, int, int]  # T, Z, Y, X
    scale: tuple[float, float, float, float]  # center-to-base-center mapping
    offset: tuple[float, float, float, float]


class _Source:
    """Public-API adapter only. Ownership stays with the library caller."""

    def __init__(self, source, channel):
        if not source.is_open:
            raise RuntimeError("Contrast estimation requires an open image or dataset")
        self.source = source
        self.dataset = callable(getattr(source, "read_block", None))
        if source.image_type == "label":
            raise ValueError("Categorical IDs are not scalar contrast intensities")
        names = source.channel_names
        if isinstance(channel, (bool, np.bool_)) or not isinstance(channel, (int, np.integer)):
            raise TypeError("channel must be an integer")
        if not 0 <= channel < len(names):
            raise IndexError("Channel outside source")
        self.channel, self.name = int(channel), names[channel]
        self.rgb = source.image_type == "rgb"
        self.samples_per_pixel = 3 if self.rgb else 1
        self.rgb_range = ((0., float(np.iinfo(source.dtype).max))
                          if self.rgb and source.dtype.kind == "u" else None)
        self.generation = getattr(source, "generation", None)
        self.scope = "dataset" if self.dataset else "image"
        if self.dataset:
            base = source.levels[0]
            self.shape = tuple(base.axis(a).size if base.axis(a) else 1 for a in "TZYX")
            levels = []
            for level in source.levels:
                shape, scale, offset = [], [], []
                for name in "TZYX":
                    a, b = base.axis(name), level.axis(name)
                    shape.append(b.size if b else 1)
                    if level.index == 0 or a is None and b is None:
                        scale.append(1.)
                        offset.append(0.)
                    elif name in "TZ" and level.plane_preserving and a.size == b.size:
                        scale.append(1.)
                        offset.append(0.)
                    elif (a is not None and b is not None and a.unit == b.unit
                          and None not in (a.scale, a.origin, b.scale, b.origin)):
                        scale.append(b.scale / a.scale)
                        offset.append((b.origin - a.origin) / a.scale)
                    else:
                        break
                else:
                    levels.append(_Level(level.index, tuple(shape), tuple(scale), tuple(offset)))
        else:
            self.shape = (1, 1, *source.levels[0].spatial_shape)
            levels = []
            for level in source.levels:
                ds, edge = level.downsample_yx, level.offset_yx
                if level.index == 0:
                    ds, edge = (1., 1.), (0., 0.)
                if ds is not None and edge is not None:
                    offset = tuple(edge[i] + (ds[i] - 1) / 2 for i in range(2))
                    levels.append(_Level(level.index, (1, 1, *level.spatial_shape),
                                         (1., 1., *ds), (0., 0., *offset)))
        self.levels = tuple(levels)
        self.has_unmapped_levels = len(levels) != len(source.levels)
        self._borrowed = None if self.dataset else source.with_metadata().open()
        if self._borrowed is not None:
            self.source = self._borrowed

    def check(self):
        if not self.source.is_open or getattr(self.source, "generation", None) != self.generation:
            raise RuntimeError("Contrast source lifetime has ended")

    def close(self):
        if self._borrowed is not None:
            self._borrowed.close()

    def read(self, t, z, bounds, level=0):
        self.check()
        if self.dataset:
            source = self.source
            context = source.plane(
                t=t if source.axis_info("T", native_level=level) else None,
                z=z if source.axis_info("Z", native_level=level) else None,
                native_level=level,
            )
            read_level = 0
        else:
            context, read_level = nullcontext(self.source), level
        with context as image:
            values = image.read_region(*bounds, level=read_level, channels=[self.channel])
            if image.axes == "CYX":
                values = values[0]
            return np.asarray(values)


class _Grid:
    """Small disjoint guide regions, aligned to the base sampling tiles.

    The guide partitions the ENTIRE population, including unvisited regions.
    Uniform mixing gives every tile positive probability even with a poor pilot.
    """

    def __init__(self, shape, tile_size):
        self.shape, self.tile_size = tuple(shape), tile_size
        self.tile_shape = (shape[0], shape[1], ceil(shape[2] / tile_size),
                           ceil(shape[3] / tile_size))
        self.edges = tuple(np.linspace(0, n, min(n, cap) + 1, dtype=np.int64)
                           for n, cap in zip(self.tile_shape, (8, 8, 16, 16)))
        self.group_shape = tuple(len(e) - 1 for e in self.edges)
        self.pixel_edges = (self.edges[0], self.edges[1],
                            np.minimum(self.edges[2] * tile_size, shape[2]),
                            np.minimum(self.edges[3] * tile_size, shape[3]))
        lengths = [np.diff(e) for e in self.pixel_edges]
        volumes = np.ones(self.group_shape, dtype=np.float64)
        for i, length in enumerate(lengths):
            s = [1] * 4
            s[i] = len(length)
            volumes *= length.reshape(s)
        self.volumes = volumes.ravel()
        self.population = prod(shape)
        self.scores = np.full(self.volumes.size, -np.inf)
        self.observed = np.zeros(self.volumes.size, dtype=bool)
        self.proposal = np.zeros(self.volumes.size)

    def groups(self, coordinates):
        ids = [np.clip(np.searchsorted(e, np.asarray(c), side="right") - 1, 0, len(e) - 2)
               for e, c in zip(self.pixel_edges, coordinates)]
        return np.ravel_multi_index(np.broadcast_arrays(*ids), self.group_shape)

    def observe(self, level, t, z, bounds, pixels):
        y0, y1, x0, x1 = bounds
        values = np.max(pixels, axis=-1) if pixels.ndim == 3 else pixels
        coordinates = [t * level.scale[0] + level.offset[0],
                       z * level.scale[1] + level.offset[1],
                       np.arange(y0, y1)[:, None] * level.scale[2] + level.offset[2],
                       np.arange(x0, x1)[None, :] * level.scale[3] + level.offset[3]]
        group = self.groups(coordinates)
        valid = np.isfinite(values)
        np.maximum.at(self.scores, group[valid], values[valid])
        self.observed[np.unique(group)] = True

    def freeze(self):
        finite = np.isfinite(self.scores)
        if not finite.any():
            return
        values = self.scores[finite]
        # Guidance only: a coarse mean is not a base-pixel percentile.
        scale = max(float(np.max(np.abs(values))), np.finfo(float).tiny)
        relative = values / scale
        scores = np.sqrt(np.maximum(relative - np.median(relative), 0.))
        self.proposal[finite] = scores
        if self.proposal.sum():
            self.proposal /= self.proposal.sum()

    def draw(self, rng, alpha):
        if not self.proposal.any() or rng.random() < alpha:
            point = tuple(int(rng.integers(n)) for n in self.shape)
        else:
            flat = int(rng.choice(self.proposal.size, p=self.proposal))
            group = np.unravel_index(flat, self.group_shape)
            point = tuple(int(rng.integers(edges[g], edges[g + 1]))
                          for g, edges in zip(group, self.pixel_edges))
        t, z, y, x = point
        iy, ix = y // self.tile_size, x // self.tile_size
        bounds = self.bounds(iy, ix)
        area = (bounds[1] - bounds[0]) * (bounds[3] - bounds[2])
        group = int(self.groups(point))
        mixed = alpha if self.proposal.any() else 1.
        density = mixed / self.population + (1 - mixed) * (
            self.proposal[group] / self.volumes[group])
        probability = area * density
        return (t, z, iy, ix), bounds, probability

    def bounds(self, iy, ix):
        s = self.tile_size
        return iy * s, min((iy + 1) * s, self.shape[2]), ix * s, min((ix + 1) * s, self.shape[3])


class ContrastEstimator:
    """Cooperatively stepped, bounded single-channel estimator.

    Construct with an already-open Omeify Image or ImageDataset. ``step`` performs
    at most one regional read (or final CPU summarization). Keep the source open,
    and serialize calls. No internal thread, disk cache, or terminal dependency.
    ``result`` is published only after the complete fixed-budget experiment.
    """

    def __init__(self, source, *, channel=0, config: ContrastConfig | None = None):
        self.config = config or ContrastConfig()
        if not isinstance(self.config, ContrastConfig):
            raise TypeError("config must be ContrastConfig")
        self._source = _Source(source, channel)
        cfg, src = self.config, self._source
        max_tile_pixels = cfg.max_base_samples // src.samples_per_pixel
        if max_tile_pixels < 1:
            src.close()
            raise ValueError("max_base_samples cannot hold one source pixel")
        # Preserve the requested number of independent draws under a tight sample
        # budget by shrinking tiles, rather than spending it on a few large tiles.
        target_draws = min(cfg.draws, max_tile_pixels)
        tile_size = min(cfg.tile_size, max(1, isqrt(max_tile_pixels)))
        census_tiles = prod(src.shape[:2]) * ceil(src.shape[2] / tile_size)
        census_tiles *= ceil(src.shape[3] / tile_size)
        if not (prod(src.shape) <= max_tile_pixels and census_tiles <= cfg.draws):
            tile_size = min(tile_size, max(1, isqrt(max_tile_pixels // target_draws)))
        self._grid = _Grid(src.shape, tile_size)
        maximum_draw_samples = min(tile_size, src.shape[2]) * min(tile_size, src.shape[3])
        maximum_draw_samples *= src.samples_per_pixel
        self._draw_limit = min(cfg.draws, cfg.max_base_samples // maximum_draw_samples)
        if self._draw_limit < 1:
            src.close()
            raise ValueError("Base-sample budget cannot hold one tile")
        self.exact = (prod(self._grid.tile_shape) <= self._draw_limit and
                      prod(src.shape) * src.samples_per_pixel <= cfg.max_base_samples)
        self._rng = np.random.default_rng(np.random.SeedSequence([cfg.seed, channel, 503]))
        self._pilot_rng = np.random.default_rng(np.random.SeedSequence([cfg.seed, channel, 211]))
        self._draws, self._coefficients, self._tile_ids = [], [], []
        self._unique = {}
        self._base_planes = set()
        self._survey_planes = set()
        self._survey_samples = self._base_samples = 0
        self._survey_reads = 0
        self._pilot_level = None
        self._pilot_total_samples = self._pilot_total_planes = 0
        self._warnings = []
        self.result: ContrastEstimate | None = None
        self.cancelled = False
        self._start = monotonic()
        if self.exact:
            self._census = iter(product(*(range(n) for n in self._grid.tile_shape)))
            self._draw_limit = prod(self._grid.tile_shape)
            self._pilot = iter(())
            self._phase = "base"
        else:
            self._census = None
            self._pilot = iter(self._plan_pilot())
            self._phase = "survey"

    def _plan_pilot(self):
        cfg, src = self.config, self._source
        if src.has_unmapped_levels:
            self._warnings.append("unmapped_pyramid_levels_not_used_for_guidance")
        if not cfg.survey_reads or not cfg.survey_samples:
            return []
        # Prefer a coarse but spatially useful plane; a 1x1 thumbnail has almost
        # no within-plane localization. XYZ is legitimate guidance, not final data.
        useful = [level for level in src.levels if all(
            level.shape[i] >= min(16, src.shape[i]) for i in (2, 3))]
        level = min(useful or src.levels, key=lambda item: prod(item.shape))
        self._pilot_level = level
        self._pilot_total_samples = prod(level.shape) * src.samples_per_pixel
        self._pilot_total_planes = prod(level.shape[:2])
        side = min(cfg.survey_tile_size,
                   max(1, int((cfg.survey_samples // src.samples_per_pixel) ** .5)))
        if cfg.survey_samples < src.samples_per_pixel:
            return []
        shape = (level.shape[0], level.shape[1], ceil(level.shape[2] / side),
                 ceil(level.shape[3] / side))
        maximum = min(side, level.shape[2]) * min(side, level.shape[3]) * src.samples_per_pixel
        count = min(prod(shape), cfg.survey_reads, cfg.survey_samples // maximum)
        ids = self._pilot_rng.choice(prod(shape), size=count, replace=False)
        tasks = []
        for index in ids:
            t, z, y, x = (int(i) for i in np.unravel_index(index, shape))
            bounds = (y * side, min((y + 1) * side, level.shape[2]),
                      x * side, min((x + 1) * side, level.shape[3]))
            tasks.append((t, z, bounds))
        if count < prod(shape):
            self._warnings.append("pilot_coverage_is_partial")
        return tasks

    @property
    def done(self):
        return self.result is not None or self.cancelled

    @property
    def progress(self):
        return {"phase": "cancelled" if self.cancelled else self._phase,
                "survey_reads": self._survey_reads, "survey_samples": self._survey_samples,
                "base_draws": len(self._draws), "planned_draws": self._draw_limit,
                "base_samples": self._base_samples}

    def close(self):
        """Release borrowed adapters; never close the caller's image/dataset."""
        if self.result is None:
            self.cancel()
        else:
            self._source.close()

    def cancel(self):
        """Call between steps. Cancellation publishes no misleading partial estimate."""
        self.cancelled = True
        self._draws.clear()
        self._coefficients.clear()
        self._tile_ids.clear()
        self._unique.clear()
        self._source.close()

    def step(self):
        """Advance one read/finalization; return whether more work remains."""
        if self.done:
            return False
        self._source.check()
        if self._phase == "survey":
            task = next(self._pilot, None)
            if task is not None:
                t, z, bounds = task
                values = self._source.read(t, z, bounds, self._pilot_level.index)
                self._grid.observe(self._pilot_level, t, z, bounds, values)
                self._survey_reads += 1
                self._survey_samples += values.size
                self._survey_planes.add((t, z))
                return True
            self._grid.freeze()
            self._phase = "base"
        if len(self._draws) < self._draw_limit:
            if self._census is not None:
                tile = next(self._census)
                t, z, iy, ix = tile
                bounds, coefficient = self._grid.bounds(iy, ix), 1.
            else:
                tile, bounds, probability = self._grid.draw(self._rng, self.config.uniform_fraction)
                t, z, _, _ = tile
                coefficient = 1. / (self._grid.population * probability)
            values = self._source.read(t, z, bounds)
            self._draws.append(values.reshape(-1).copy())
            self._coefficients.append(coefficient)
            self._tile_ids.append(tile)
            self._unique[tile] = values.size
            self._base_planes.add((t, z))
            self._base_samples += values.size
            return True
        self._phase = "summarize"
        summary = summarize_draws(self._draws, self._coefficients, self._tile_ids,
                                  config=self.config, exact=self.exact,
                                  rgb_range=self._source.rgb_range)
        warnings = tuple(dict.fromkeys((*self._warnings, *summary.pop("warnings"))))
        if not self.exact and not self._grid.proposal.any():
            warnings += ("pilot_uninformative_uniform_sampling",)
        self.result = ContrastEstimate(
            channel=self._source.channel, channel_name=self._source.name,
            scope=self._source.scope, method="census" if self.exact else "defensive-tile-is/1",
            policy="rgb-native" if self._source.rgb_range else self.config.upper_policy,
            exact=self.exact, population_samples=prod(self._source.shape) *
            self._source.samples_per_pixel, sampled_samples=self._base_samples,
            unique_sampled_samples=sum(self._unique.values()), draw_count=len(self._draws),
            unique_tiles=len(self._unique),
            survey_level=None if self._pilot_level is None else self._pilot_level.index,
            survey_reads=self._survey_reads, survey_samples=self._survey_samples,
            survey_total_samples=self._pilot_total_samples,
            survey_planes=len(self._survey_planes), survey_total_planes=self._pilot_total_planes,
            base_planes=len(self._base_planes), total_base_planes=prod(self._source.shape[:2]),
            base_reads=len(self._draws), elapsed_seconds=monotonic() - self._start,
            warnings=warnings, config=self.config, **summary,
        )
        self._draws.clear()
        self._coefficients.clear()
        self._tile_ids.clear()
        self._phase = "complete"
        self._source.close()
        return False


def estimate_contrast(source, *, channel=0, config=None):
    """Run the same fixed-budget estimator synchronously; source remains caller-owned."""
    estimator = ContrastEstimator(source, channel=channel, config=config)
    try:
        while estimator.step():
            pass
        return estimator.result
    finally:
        estimator.close()
