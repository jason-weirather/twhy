"""Weighted base-pixel distributions and explicit display policies.

The sampling unit is a *tile draw*, not an individual correlated pixel.
Nothing here opens a file, starts a worker, or imports the terminal frontend.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from math import isfinite

import numpy as np

from .intensity_window import IntensityWindow


@dataclass(frozen=True, slots=True)
class ContrastConfig:
    """Fixed work budgets per channel. Bounds count returned samples, not codec I/O.

    A fixed seed makes the planned experiment reproducible. Changing a budget
    defines a different experiment; there is no data-dependent early stopping.
    """

    seed: int = 0
    tile_size: int = 32
    draws: int = 128
    max_base_samples: int = 131_072
    survey_reads: int = 128
    survey_samples: int = 262_144
    survey_tile_size: int = 128
    uniform_fraction: float = 0.5
    lower_quantile: float = 0.01
    upper_quantile: float = 0.995
    highlight_quantile: float = 0.995
    upper_policy: str = "highlight"
    bootstrap_replicates: int = 48
    histogram_bins: int = 128

    def __post_init__(self):
        for name in ("seed", "tile_size", "draws", "max_base_samples", "survey_reads",
                     "survey_samples", "survey_tile_size", "bootstrap_replicates",
                     "histogram_bins"):
            value = getattr(self, name)
            minimum = 0 if name in ("seed", "survey_reads", "survey_samples",
                                     "bootstrap_replicates") else 1
            if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
                raise TypeError(f"{name} must be an integer")
            object.__setattr__(self, name, int(value))
            if value < minimum:
                raise ValueError(f"{name} must be >= {minimum}")
        for name in ("uniform_fraction", "lower_quantile", "upper_quantile",
                     "highlight_quantile"):
            value = getattr(self, name)
            if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float,
                                                                           np.number)):
                raise TypeError(f"{name} must be a real number")
            object.__setattr__(self, name, float(value))
        if not isfinite(self.uniform_fraction) or not 0.1 <= self.uniform_fraction <= 1:
            raise ValueError("uniform_fraction must be in [0.1, 1]")
        if not 0 <= self.lower_quantile < self.upper_quantile <= 1:
            raise ValueError("Quantiles must satisfy 0 <= lower < upper <= 1")
        if not 0 < self.highlight_quantile <= 1:
            raise ValueError("highlight_quantile must be in (0, 1]")
        if self.upper_policy not in ("highlight", "percentile"):
            raise ValueError("upper_policy must be 'highlight' or 'percentile'")
        if self.histogram_bins < 2:
            raise ValueError("histogram_bins must be >= 2")


def weighted_quantile(values, weights, probability):
    """Inverse weighted empirical CDF, with no interpolation across empty gaps."""
    x, w = np.asarray(values, dtype=np.float64), np.asarray(weights, dtype=np.float64)
    if x.ndim != 1 or w.shape != x.shape or not x.size:
        raise ValueError("Nonempty matching one-dimensional values/weights required")
    if not 0 <= probability <= 1:
        raise ValueError("Quantile probability must be in [0, 1]")
    if not np.isfinite(x).all() or not np.isfinite(w).all() or np.any(w < 0):
        raise ValueError("Values and nonnegative weights must be finite")
    positive = w > 0
    if not positive.any():
        raise ValueError("At least one positive weight required")
    order = np.argsort(x[positive], kind="stable")
    # A common rescaling preserves the weighted CDF and avoids overflow for
    # otherwise valid very large public weights. Production tile weights are bounded.
    weights = w[positive][order]
    weights = weights / weights.max()
    return _sorted_quantile(x[positive][order], weights, probability)


def _sorted_quantile(x, w, p):
    cumulative = np.cumsum(w, dtype=np.float64)
    index = np.searchsorted(cumulative, p * cumulative[-1], side="left")
    # At p=0 skip zero-mass entries (bootstrap replicates can omit tiles).
    if p == 0:
        index = np.flatnonzero(w > 0)[0]
    return float(x[min(int(index), len(x) - 1)])


def _limits(x, weights, config, rgb_range=None):
    if rgb_range is not None:
        return IntensityWindow(*rgb_range)
    low = _sorted_quantile(x, weights, config.lower_quantile)
    high = _sorted_quantile(x, weights, config.upper_quantile)
    if config.upper_policy == "highlight":
        # Scale before subtraction: do not overflow when finite values straddle 0.
        scale = max(float(np.max(np.abs(x))), abs(low), np.finfo(float).tiny)
        excess = np.maximum(x / scale - low / scale, 0.)
        highlight_weights = weights * excess
        if highlight_weights.sum() > 0:
            high = max(high, _sorted_quantile(x, highlight_weights, config.highlight_quantile))
    if high <= low:
        positive = weights > 0
        low, high = float(x[positive][0]), float(x[positive][-1])
    if high <= low:
        if high > 0:
            low = 0.
        else:
            high = max(low + 1., float(np.nextafter(low, np.inf)))
    return IntensityWindow(low, high)


@dataclass(frozen=True, slots=True)
class ContrastEstimate:
    """Detached finite-base-pixel histogram and a separately identified display rule.

    Intervals are approximate conditional, fixed-budget tile-bootstrap intervals.
    They cannot certify detection of an unsampled rare object or validate a
    biological notion of signal. No confidence level is assigned to that claim.
    """

    window: IntensityWindow | None
    channel: int
    channel_name: str
    scope: str
    method: str
    policy: str
    exact: bool
    population_samples: int
    sampled_samples: int
    unique_sampled_samples: int
    draw_count: int
    unique_tiles: int
    survey_level: int | None
    survey_reads: int
    survey_samples: int
    survey_total_samples: int
    survey_planes: int
    survey_total_planes: int
    base_planes: int
    total_base_planes: int
    base_reads: int
    finite_fraction: float
    draw_weight_ess: float
    upper_support_tiles: int
    lower_interval: tuple[float, float] | None
    upper_interval: tuple[float, float] | None
    elapsed_seconds: float
    warnings: tuple[str, ...]
    config: ContrastConfig
    bin_edges: np.ndarray = field(repr=False, compare=False)
    probability: np.ndarray = field(repr=False, compare=False)
    _values: np.ndarray = field(repr=False, compare=False)
    _weights: np.ndarray = field(repr=False, compare=False)

    def __post_init__(self):
        for name in ("bin_edges", "probability", "_values", "_weights"):
            array = np.array(getattr(self, name), dtype=np.float64, copy=True)
            array.flags.writeable = False
            object.__setattr__(self, name, array)

    @property
    def nbytes(self) -> int:
        """Retained array bytes, excluding Python records and temporary workspace."""
        return sum(array.nbytes for array in
                   (self.bin_edges, self.probability, self._values, self._weights))

    def cdf(self, value: float) -> float:
        """Estimated fraction of finite base samples <= value, not coarse pixels."""
        if not self._values.size:
            return float("nan")
        return float(self._weights[self._values <= value].sum() / self._weights.sum())

    def clipped_fraction(self, upper: float) -> float:
        return 1. - self.cdf(upper)

    def histogram(self, bins=128, *, value_range=None):
        """Rebin retained weighted samples without further source reads."""
        if value_range is None:
            value_range = (float(self.bin_edges[0]), float(self.bin_edges[-1]))
        counts, edges = np.histogram(self._values, bins=bins, range=value_range,
                                    weights=self._weights)
        total = self._weights.sum()
        if total:
            counts = counts / total
        return edges, counts

    def to_dict(self, *, include_histogram=True):
        """JSON-compatible, versioned report; no private paths, NaNs, or live handles."""
        excluded = {"bin_edges", "probability", "_values", "_weights", "config", "window"}
        result = {name: getattr(self, name) for name in self.__dataclass_fields__
                  if name not in excluded}
        result.update(schema="twhy.contrast/1", config=asdict(self.config),
                      window=None if self.window is None else asdict(self.window),
                      uncertainty="exact census" if self.exact else
                      "approximate pointwise 95% tile bootstrap conditional on pilot; "
                      "not a rare-feature detection guarantee")
        if include_histogram:
            result["histogram"] = {"edges": self.bin_edges.tolist(),
                                   "probability": self.probability.tolist(),
                                   "population": "finite base-resolution scalar samples"}
        return result


def summarize_draws(draws, coefficients, tile_ids, *, config, exact, rgb_range=None):
    """HH/Hajek ratio distribution, resampling whole independently selected tiles.

    ``coefficients[j]`` is the per-pixel inverse draw-probability weight for
    draw j (common scale immaterial). Census draws all have unit coefficients.
    Bootstrap resamples draw occurrences, NOT unique tiles and NOT pixels.
    """
    warnings = []
    arrays = [np.asarray(a, dtype=np.float64).reshape(-1) for a in draws]
    values = np.concatenate(arrays)
    groups = np.repeat(np.arange(len(arrays)), [a.size for a in arrays])
    coefficients = np.asarray(coefficients, dtype=np.float64)
    weights = coefficients[groups]
    total_mass = weights.sum()
    finite = np.isfinite(values)
    finite_fraction = float(weights[finite].sum() / total_mass)
    if not finite.all():
        warnings.append("nonfinite_samples_excluded")
    x, w, g = values[finite], weights[finite], groups[finite]
    order = np.argsort(x, kind="stable")
    x, w, g = x[order], w[order], g[order]
    cluster_mass = np.bincount(groups, weights=weights, minlength=len(arrays))
    ess = float(cluster_mass.sum() ** 2 / np.dot(cluster_mass, cluster_mass))
    if not x.size:
        return dict(window=None, finite_fraction=finite_fraction, draw_weight_ess=ess,
                    upper_support_tiles=0, lower_interval=None, upper_interval=None,
                    warnings=tuple(warnings + ["no_finite_samples"]),
                    bin_edges=np.linspace(0., 1., config.histogram_bins + 1),
                    probability=np.zeros(config.histogram_bins), _values=x, _weights=w)
    window = _limits(x, w, config, rgb_range)
    tail = x >= window.upper
    tail_ids = {tile_ids[int(i)] for i in np.unique(g[tail])}
    support = len(tail_ids)
    if not exact:
        warnings.append("unsampled_rare_signal_may_exist")
        if len(set(tile_ids)) < 16:
            warnings.append("few_independent_spatial_tiles")
        if support < 4:
            warnings.append("upper_tail_supported_by_fewer_than_four_tiles")
    low_ci = high_ci = None
    if exact:
        low_ci, high_ci = (window.lower,) * 2, (window.upper,) * 2
    elif config.bootstrap_replicates >= 20 and len(arrays) >= 16 and support >= 4:
        rng = np.random.default_rng(np.random.SeedSequence([config.seed, 941]))
        limits = []
        for _ in range(config.bootstrap_replicates):
            frequency = rng.multinomial(len(arrays), np.full(len(arrays), 1. / len(arrays)))
            bw = w * frequency[g]
            if bw.sum():
                estimate = _limits(x, bw, config, rgb_range)
                limits.append((estimate.lower, estimate.upper))
        if limits:
            limits = np.quantile(limits, [.025, .975], axis=0)
            low_ci, high_ci = tuple(map(float, limits[:, 0])), tuple(map(float, limits[:, 1]))
    if not exact and high_ci is None:
        warnings.append("cutoff_interval_unavailable_or_tail_under_supported")
    if x[0] == x[-1]:
        warnings.append("constant_sample")
    lo, hi = min(float(x[0]), window.lower), max(float(x[-1]), window.upper)
    if not isfinite(hi - lo):
        raise ValueError("Intensity span exceeds the float64 display range")
    probability, edges = np.histogram(x, bins=config.histogram_bins, range=(lo, hi), weights=w)
    probability /= w.sum()
    return dict(window=window, finite_fraction=finite_fraction, draw_weight_ess=ess,
                upper_support_tiles=support, lower_interval=low_ci, upper_interval=high_ci,
                warnings=tuple(warnings), bin_edges=edges, probability=probability,
                _values=x, _weights=w)
