"""File-free text histogram rendering, with explicit limit-handle coordinates."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from wcwidth import wcwidth

from ._validation import positive_integer
from .contrast_statistics import ContrastEstimate
from .intensity_window import IntensityWindow
from .text_image import TextImage


@dataclass(frozen=True, slots=True)
class HistogramView:
    frame: TextImage
    left: int
    right: int
    handle_row: int
    lower_column: int
    upper_column: int
    minimum: float
    maximum: float

    def value_at(self, column: int) -> float:
        fraction = np.clip((column - self.left) / max(1, self.right - self.left), 0., 1.)
        if fraction == 0:
            return self.minimum
        if fraction == 1:
            return self.maximum
        return float(self.minimum + fraction * (self.maximum - self.minimum))


def render_histogram(estimate: ContrastEstimate, *, window: IntensityWindow | None = None,
                     columns=80, rows=24, log_counts=True, color=None, ascii_only=False):
    """Render estimated finite base-sample probability, never the pilot histogram.

    The plot uses linear raw intensity on X; log_counts changes only the count
    axis. Carets are display-window controls, not segmentation thresholds.
    """
    columns, rows = positive_integer(columns, "columns"), positive_integer(rows, "rows")
    chars = np.full((rows, columns), " ", dtype="U1")

    def text(row, content, left=1):
        if 0 <= row < rows:
            content = "".join(c if c.isprintable() and wcwidth(c) == 1 and
                              (not ascii_only or c.isascii()) else "?" for c in content)
            content = content[:max(0, columns - left)]
            chars[row, left:left + len(content)] = list(content)

    window = window or estimate.window
    lo, hi = float(estimate.bin_edges[0]), float(estimate.bin_edges[-1])
    if window is not None:
        lo, hi = min(lo, window.lower), max(hi, window.upper)
    if hi <= lo:
        hi = lo + 1
    if not np.isfinite(hi - lo):
        raise ValueError("Histogram display span exceeds float64 range")
    if columns < 24 or rows < 12:
        text(0, "Histogram: enlarge terminal")
        text(1, f"Channel {estimate.channel}: {estimate.channel_name}")
        return HistogramView(TextImage(chars), 0, max(1, columns - 1), -1, 0, 0, lo, hi)
    left, right = 2, columns - 3
    width = right - left + 1
    top, baseline = 3, rows - 7
    handle_row = baseline + 1
    text(0, f"HISTOGRAM  C{estimate.channel}: {estimate.channel_name}  [{estimate.scope}]")
    mode = "exact census" if estimate.exact else "weighted base-pixel estimate"
    text(1, f"{mode} | {'log' if log_counts else 'linear'} count | {estimate.policy}")
    text(2, "H:image L:log A:apply estimate | l/u:edit | drag ^L/^U")
    _, mass = estimate.histogram(width, value_range=(lo, hi))
    counts = mass * estimate.population_samples * estimate.finite_fraction
    heights = np.log1p(counts) if log_counts else counts
    maximum = heights.max(initial=0.)
    heights = heights / maximum * (baseline - top) if maximum else heights
    chars[baseline, left:right + 1] = "-"
    chars[top:baseline + 1, left - 1] = "|"
    glyphs = " ▁▂▃▄▅▆▇█"
    for x, height in enumerate(heights):
        for row in range(top, baseline):
            coverage = np.clip(height - (baseline - row - 1), 0., 1.)
            if coverage > 0:
                chars[row, left + x] = "#" if ascii_only else glyphs[int(np.ceil(coverage * 8))]
    def column(value):
        return int(round(left + np.clip((value - lo) / (hi - lo), 0., 1.) * (right - left)))
    lower = column(window.lower if window else lo)
    upper = column(window.upper if window else hi)
    chars[handle_row, lower] = "^"
    chars[handle_row, upper] = "^"
    if lower + 1 < right:
        chars[handle_row, lower + 1] = "L" if lower != upper else "*"
    if upper + 1 < columns and lower != upper:
        chars[handle_row, upper + 1] = "U"
    text(handle_row + 1, f"{lo:.5g}", left)
    label = f"{hi:.5g}"
    text(handle_row + 1, label, max(left + 10, right - len(label) + 1))
    if window:
        clipping = estimate.clipped_fraction(window.upper)
        below = estimate.cdf(float(np.nextafter(window.lower, -np.inf)))
        text(handle_row + 2, f"L {window.lower:.6g}  U {window.upper:.6g} | "
             f"<L ~{100 * below:.3g}% >U ~{100 * clipping:.3g}%")
    else:
        text(handle_row + 2, "No finite samples: no suggested window")
    text(handle_row + 3, f"Base: {estimate.unique_tiles} tiles, "
         f"{estimate.base_planes}/{estimate.total_base_planes} Z/T planes; "
         f"{estimate.sampled_samples:,} samples")
    interval = ("exact census cutoff" if estimate.exact else
                "suggested U interval unavailable" if estimate.upper_interval is None else
                f"suggested U ~95% [{estimate.upper_interval[0]:.4g}, "
                f"{estimate.upper_interval[1]:.4g}]")
    pilot = ("No pilot" if estimate.survey_level is None else
             f"Pilot L{estimate.survey_level}: {estimate.survey_samples:,}")
    text(handle_row + 4, f"{pilot} | {interval}")
    # Surface the important rare-tail warning, not only a generic partial-coverage flag.
    warning = next((w for w in estimate.warnings if "upper_tail" in w),
                   estimate.warnings[0] if estimate.warnings else "")
    text(handle_row + 5, ("! " + warning.replace("_", " ")) if warning else
         "Drag ^L/^U; l/u: exact values. Source pixels unchanged.")
    foreground = None
    if color is not None:
        rgb = np.asarray(color, dtype=float)
        if rgb.shape != (3,) or not np.isfinite(rgb).all() or np.any((rgb < 0) | (rgb > 1)):
            raise ValueError("color must be a normalized RGB triple")
        foreground = np.full((*chars.shape, 3), 210, dtype=np.uint8)
        foreground[top:baseline, left:right + 1] = np.rint(rgb * 255).astype(np.uint8)
        foreground[handle_row, [lower, upper]] = (255, 215, 95)
    return HistogramView(TextImage(chars, foreground=foreground), left, right, handle_row,
                         lower, upper, lo, hi)
