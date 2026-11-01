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


def _number(value: float, *, compact: bool = False) -> str:
    """Tick labels are compact, not a change to the underlying raw coordinates."""
    if compact:
        for scale, suffix in ((1e12, "T"), (1e9, "G"), (1e6, "M"), (1e3, "k")):
            if abs(value) >= scale:
                return f"{value / scale:.3g}{suffix}"
    return f"{value:.4g}"


def _ticks(lo: float, hi: float, count: int) -> list[float]:
    """Endpoints plus a small number of nice, bounded interior tick positions."""
    span = hi - lo
    raw = span / max(1, count - 1)
    if raw <= 0 or not np.isfinite(raw):
        return [lo, hi]
    exponent = np.floor(np.log10(raw))
    power = float(10. ** exponent)
    if power == 0:
        return [lo, hi]
    fraction = raw / power
    step = next((s for s in (1., 2., 2.5, 5., 10.) if s >= fraction), 10.) * power
    if not np.isfinite(step) or step <= 0 or not np.isfinite(lo / step):
        return [lo, hi]
    first = np.ceil(lo / step) * step
    return [lo, hi, *(float(v) for i in range(count + 1)
                     if lo < (v := first + i * step) < hi)]


def render_histogram(estimate: ContrastEstimate, *, window: IntensityWindow | None = None,
                     columns=80, rows=24, log_counts=True, color=None, ascii_only=False):
    """Render estimated finite base-sample probability, never the pilot histogram.

    X is linear raw intensity. Log counts use log1p, as in the original renderer.
    One bin per plot column is drawn without smoothing or tail truncation. The
    outline and subdued fill show the same bin heights; clipped portions are
    dimmed, not removed. The rail/guide marks are display-window controls, not
    segmentation thresholds. A monochrome/strict-ASCII form needs no ANSI colors.
    """
    columns, rows = positive_integer(columns, "columns"), positive_integer(rows, "rows")
    chars = np.full((rows, columns), " ", dtype="U1")
    # Deliberately match the viewer's dark chrome without depending on its frontend.
    palette = {
        "text": (214, 224, 238), "muted": (139, 159, 183), "axis": (75, 97, 124),
        "grid": (32, 46, 65), "lower": (131, 213, 200), "upper": (255, 215, 119),
        "warning": (235, 188, 109), "background": (12, 19, 30),
        "header": (20, 28, 41),
    }
    fg = bg = None
    if color is not None:
        rgb = np.asarray(color, dtype=float)
        if rgb.shape != (3,) or not np.isfinite(rgb).all() or np.any((rgb < 0) | (rgb > 1)):
            raise ValueError("color must be a normalized RGB triple")
        ink = np.rint(rgb * 255).astype(np.uint8)
        fg = np.full((*chars.shape, 3), palette["text"], dtype=np.uint8)
        bg = np.full((*chars.shape, 3), palette["background"], dtype=np.uint8)
        bg[:2] = palette["header"]

    def text(row, content, left=1, *, tone="text", stop=None):
        if not 0 <= row < rows:
            return
        content = "".join(c if c.isprintable() and wcwidth(c) == 1 and
                          (not ascii_only or c.isascii()) else "?" for c in content)
        content = content[:max(0, min(columns, columns if stop is None else stop) - left)]
        chars[row, left:left + len(content)] = list(content)
        if fg is not None:
            fg[row, left:left + len(content)] = palette[tone]

    def line(row, start, end, glyph, tone="axis"):
        chars[row, start:end] = glyph
        if fg is not None:
            fg[row, start:end] = palette[tone]

    def blend(a, b, amount):
        return np.rint(np.asarray(a) * (1 - amount) + np.asarray(b) * amount).astype(np.uint8)

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
        text(1, f"Channel {estimate.channel}: {estimate.channel_name}", tone="muted")
        return HistogramView(TextImage(chars, foreground=fg, background=bg),
                             0, max(1, columns - 1), -1, 0, 0, lo, hi)

    compact = rows < 18
    left, right = (8 if columns >= 80 else 6 if columns >= 40 else 2), columns - 3
    width = right - left + 1
    top, baseline = (2, rows - 7) if compact else (3, rows - 9)
    handle_row = baseline + 2
    plot_height = baseline - top
    sep = " | " if ascii_only else " · "
    badge = f"[{estimate.scope}]"
    badge_left = columns - len(badge) - 2
    text(0, f"HISTOGRAM  C{estimate.channel}: {estimate.channel_name}",
         stop=badge_left - 1 if columns >= 45 else columns - 1)
    if columns >= 45:
        text(0, badge, badge_left, tone="lower")
    mode = "exact census" if estimate.exact else (
        "weighted base-pixel estimate" if columns >= 70 else "weighted estimate")
    text(1, sep.join((mode, "log count" if log_counts else "linear count", estimate.policy)),
         tone="muted")

    # Linear counts are estimated pixel counts, not a number of independent trials.
    _, mass = estimate.histogram(width, value_range=(lo, hi))
    counts = mass * estimate.population_samples * estimate.finite_fraction
    transformed = np.log1p(counts) if log_counts else counts
    peak = transformed.max(initial=0.)
    heights = transformed / peak * plot_height if peak else transformed

    def column(value):
        return int(round(left + np.clip((value - lo) / (hi - lo), 0., 1.) * (right - left)))

    lower = column(window.lower if window else lo)
    upper = column(window.upper if window else hi)
    axis, rule = ("|", "-") if ascii_only else ("│", "─")
    grid = "." if ascii_only else "·"
    chars[top:baseline + 1, left - 1] = axis
    if fg is not None:
        fg[top:baseline + 1, left - 1] = palette["axis"]
    # Sparse horizontal guides, with literal count labels on a log or linear axis.
    for fraction in (0., .5, 1.):
        y = baseline - int(round(plot_height * fraction))
        amount = (np.expm1(peak * fraction) if log_counts else peak * fraction)
        if left >= 6:
            label = _number(float(amount), compact=True)
            text(y, label[-(left - 2):].rjust(left - 2), 0, tone="muted")
        if y < baseline:
            chars[y, left:right + 1:4] = grid
            if fg is not None:
                fg[y, left:right + 1:4] = palette["grid"]

    glyphs = " ▁▂▃▄▅▆▇█"
    for x, height in enumerate(heights):
        inside = lower <= left + x <= upper
        for y in range(top, baseline):
            coverage = float(np.clip(height - (baseline - y - 1), 0., 1.))
            if coverage <= 0:
                continue
            edge = height <= baseline - y
            chars[y, left + x] = ("#" if edge else ":") if ascii_only else (
                "░" if fg is None and not edge else glyphs[int(np.ceil(coverage * 8))])
            if fg is not None:
                if edge:
                    fg[y, left + x] = (ink if inside else blend(palette["background"], ink, .48))
                else:
                    strength = (.22 + .20 * (baseline - y) / plot_height) if inside else .13
                    fg[y, left + x] = blend(palette["background"], ink, strength)
    line(baseline, left, right + 1, rule)
    chars[baseline, left - 1] = "+" if ascii_only else "└"

    # Endpoints have priority. Interior numeric labels never overlap each other.
    occupied = np.zeros(columns, dtype=bool)
    for value in _ticks(lo, hi, max(2, min(5, width // 13))):
        x = column(value)
        label = _number(value, compact=True)
        start = max(left, min(right - len(label) + 1, x - len(label) // 2))
        end = min(columns, start + len(label))
        if occupied[max(0, start - 1):min(columns, end + 1)].any():
            continue
        text(baseline + 1, label, start, tone="muted")
        occupied[start:end] = True
        chars[baseline, x] = "+" if ascii_only else "┬"

    # The slider rail is distinct from histogram counts. It shows the display ramp.
    line(handle_row, left, right + 1, "-" if ascii_only else "─")
    for x in range(lower, upper + 1):
        chars[handle_row, x] = "=" if ascii_only else "━"
        if fg is not None:
            strength = .25 + .75 * (x - lower) / max(1, upper - lower)
            fg[handle_row, x] = blend(palette["background"], ink, strength)
    for x, tone in ((lower, "lower"), (upper, "upper")):
        # Guides are above the bars only: they do not punch holes through the data.
        height = heights[x - left]
        for y in range(top, baseline):
            if (y - top) % 2 == 0 and height < baseline - y - 1:
                chars[y, x] = ":" if ascii_only else "┊"
                if fg is not None:
                    fg[y, x] = blend(palette["background"], palette[tone], .5)
        chars[handle_row, x] = "^" if ascii_only else "▲"
        if fg is not None:
            fg[handle_row, x] = palette[tone]
    if lower == upper:
        chars[handle_row, lower] = "^" if ascii_only else "◆"

    if window is not None:
        lvalue = f"{window.lower:.6g}" if columns >= 70 else _number(window.lower, compact=True)
        uvalue = f"{window.upper:.6g}" if columns >= 70 else _number(window.upper, compact=True)
        llabel, ulabel = f"L {lvalue}", f"U {uvalue}"
        lstart = max(left, min(right - len(llabel) + 1, lower - len(llabel) // 2))
        ustart = max(left, min(right - len(ulabel) + 1, upper - len(ulabel) // 2))
        if ustart < lstart + len(llabel) + 2:
            lstart = max(left, min(lstart, ustart - len(llabel) - 2))
            ustart = max(ustart, lstart + len(llabel) + 2)
        text(handle_row + 1, llabel, lstart, tone="lower", stop=ustart - 1)
        text(handle_row + 1, ulabel, ustart, tone="upper")
        below = estimate.cdf(float(np.nextafter(window.lower, -np.inf)))
        above = estimate.clipped_fraction(window.upper)
        clipping = f"Clipped <L ~{100 * below:.3g}%  >U ~{100 * above:.3g}%"
    else:
        clipping = "No finite samples: no suggested window"
        text(handle_row + 1, clipping, 1, tone="warning")
    samples = (f"Base {estimate.unique_tiles} tiles{sep}"
               f"{estimate.base_planes}/{estimate.total_base_planes} Z/T{sep}"
               f"{estimate.sampled_samples:,} samples")
    interval = ("exact census cutoff" if estimate.exact else
                "Suggested U interval unavailable" if estimate.upper_interval is None else
                f"Suggested U ~95% [{_number(estimate.upper_interval[0], compact=True)}, "
                f"{_number(estimate.upper_interval[1], compact=True)}]")
    pilot = ("No pilot" if estimate.survey_level is None else
             f"Pilot L{estimate.survey_level}: {_number(estimate.survey_samples, compact=True)}")
    warning = next((w for w in estimate.warnings if "upper_tail" in w),
                   estimate.warnings[0] if estimate.warnings else "")
    warning = warning.replace("_", " ")
    if compact:
        text(handle_row + 2, clipping, tone="muted")
        text(handle_row + 3, "! " + warning if warning else samples,
             tone="warning" if warning else "muted")
        text(rows - 1, "H image  A estimate/apply  L log  l/u edit", tone="muted")
    else:
        text(handle_row + 2, clipping, tone="muted")
        text(handle_row + 3, samples, tone="muted")
        # Keep the cutoff interval visible at compact widths; the pilot is secondary.
        details = interval + sep + pilot
        text(handle_row + 4, details, tone="muted")
        text(handle_row + 5, "! " + warning if warning else
             "Display limits only; source pixels unchanged.",
             tone="warning" if warning else "muted")
        text(rows - 1, "H image  A estimate/apply  L log/linear  l/u edit  drag " +
             ("^" if ascii_only else "▲"), tone="muted")
    if bg is not None:
        bg[rows - 1] = palette["header"]
    return HistogramView(TextImage(chars, foreground=fg, background=bg), left, right, handle_row,
                         lower, upper, lo, hi)
