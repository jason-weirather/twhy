# Fast, pyramid-guided contrast and text histograms

This is a versioned, bounded sampling method and a separate display policy, not
an assertion that a picture has one scientifically correct contrast range.
The implementation lives in **twhy**. Omeify supplies unchanged pixels, pyramid
geometry, regional access, caches, and resource ownership. No Omeify files or
reader contracts are changed.

## Use it

In the viewer, **H** switches the canvas between image and histogram. The plot
follows the focused channel. Clicking a channel name while viewing a histogram
changes focus without toggling that channel's image visibility. **L** changes
only the histogram's count axis between log and linear; intensities stay linear
and in raw units. Drag **^L** or **^U**, or use the existing **l/u** numeric entry.
The current clipped fractions are estimated from the weighted base-pixel sample.
Intervals refer to the *suggested* cutoff, not a manually dragged limit.

**A** applies the focused channel's dataset/image recommendation, estimating it
if needed. **a** retains the earlier visible-preview auto-window behavior. An
explicit adjustment, including a/gamma/limit editing, protects that channel from
an automatic result already in flight. H alone does not apply a recommendation.

Interactive scalar stacks begin at middle Z (`size // 2`) and T=0, unless explicit
indices are supplied. The existing preview window is provisional. The viewer
incrementally estimates each selected channel's dataset-wide range and applies
it once when ready. Z/T, pan and zoom never automatically recalculate that range.
A different series gets separate estimates. `--no-stack-contrast` disables the
initial automatic work; H and A remain available. An explicit startup window is
never automatically replaced. Ordinary 2D startup and snapshot contrast retain
their prior policy; snapshots now share the middle-Z startup choice.

### Public library

```python
from omeify import open_dataset
from twhy import ContrastConfig, estimate_contrast, render_histogram

with open_dataset("experiment.zarr", input_type="ome_zarr") as dataset:
    result = estimate_contrast(dataset, channel=0, config=ContrastConfig(seed=17))
    print(result.window)
    report = result.to_dict()  # twhy.contrast/1; JSON-compatible detached values
    print(result.cdf(1200))
    print(result.clipped_fraction(12000))

# The result contains owned, read-only samples and needs no live source.
plot = render_histogram(result, columns=100, rows=28, ascii_only=True)
print(plot.frame.to_text())
```

An already-open ordinary Omeify Image is accepted too. Its scope is that fixed
observation, not an implicitly discovered stack. A selected ImageDataset describes
only its explicitly selected population. Neither path imports the terminal UI,
opens another decoder, creates a temporary image, or changes source values.
Categorical label IDs are rejected. RGB remains one logical channel: its samples
are pooled for the histogram, and unsigned RGB retains its native display range.

`ContrastEstimator(source, channel=..., config=...)` exposes the same engine as a
cooperative job. Call `step()` until it returns False, then inspect `result`.
Each step performs at most one regional read, or final CPU summarization. Keep
the source open; serialize steps. `cancel()` between steps discards unfinished
results. `close()` releases borrowed adapters, never the caller's source. Calls
are synchronous and cannot interrupt an in-flight codec or network request.

## 1. Define the population before choosing the display

For one scalar channel, the population is the base-resolution samples over all
T/Z/Y/X positions of the supplied dataset, or Y/X of an Image. Each voxel has
equal weight; irregular acquisition times are not interpreted as durations.
Nonfinite values are excluded from the intensity CDF and reported separately.
Zero is a valid value, not an automatic background mask.

Disjoint XY tiles within each T/Z plane are the sampling units. Edge tiles have
their actual, possibly smaller area. All pixels in a selected tile are read.
This cluster design exploits regional I/O while recognizing that adjacent pixels
are not independent replicates for uncertainty calculations.

Small populations are enumerated exactly when the complete tile inventory fits
both the draw and base-sample budgets. There is then no sampling uncertainty,
although the choice of a *useful display* remains a policy decision.

## 2. Freeze an inexpensive pilot before final sampling

The pilot selects one coarse, spatially useful native level with a declared
mapping to base coordinates. It prefers planes retaining at least 16 pixels in
each spatial direction where the source permits it. XYZ levels may guide the
search: they are not substituted for exact sections in normal image viewing.
Unknown transforms are not guessed from rounded shape ratios. Such levels are
omitted with a warning; base-resolution exploration remains possible.

The entire population is divided into at most 8 x 8 x 16 x 16 T/Z/Y/X guide
regions, aligned with base tile boundaries. The pilot visits all coarse read
regions when affordable, otherwise a seeded random subset without replacement.
Its maximum observed finite intensity scores each visited guide region. Scores
are scaled, centered on their median, clipped below zero, and square-rooted.
The nonnegative scores normalize into a guide-region proposal. Unvisited or
unhelpful regions remain eligible through the uniform component below.

Coarse samples, including averaged/diluted values, **never enter the final
histogram or clipping quantiles**. The guide is frozen before independent base
draws begin. This first implementation does not repeatedly adapt the proposal
using its final samples or stop early when an observed cutoff looks stable.

## 3. Defensive importance sampling with known probabilities

Let N be the number of base spatial voxels, a_j the area of tile j, g(j) its guide
region, N_g that region's voxel count, and r_g its normalized guide probability.
With default uniform mixture fraction alpha=0.5, each draw selects tile j with

```
q_j = a_j * [alpha / N + (1 - alpha) * r_g(j) / N_g(j)] .
```

Implementation: choose a uniform base voxel with probability alpha, otherwise
choose a guide region according to r and a uniform voxel inside it; read the
whole tile containing that voxel. Draws are independent **with replacement**.
Duplicate draws are retained as sampling occurrences, although the source cache
may avoid repeated storage work. An uninformative pilot becomes pure uniform
voxel-to-tile sampling.

Every tile has positive probability. Its population-area weight p_j=a_j/N obeys
`p_j/q_j <= 1/alpha`. The defensive component therefore bounds importance ratios;
it does not guarantee that a rare object will be found. This follows the
established defensive-mixture importance-sampling idea [1,2].

Each finite pixel in draw j receives weight proportional to `1/q_j`. Common
scales cancel. The reported distribution is

```
F_hat(v) = sum_draws sum_pixels_in_draw [1(x <= v) / q_draw]
           / sum_draws sum_finite_pixels_in_draw [1 / q_draw] .
```

The pre-normalized Hansen-Hurwitz totals are design-unbiased conditional on the
frozen pilot. The normalized CDF is a ratio estimator, and its inverted quantiles
are **not claimed to be exactly unbiased**. The inverse empirical CDF does not
interpolate across empty intensity gaps. Unequal-probability CDF/quantile
estimation has established literature [3]; this is not a new statistical theorem.

This removes the naive bias from pretending that heavily targeted bright tiles
occupy the same population share as their fraction of collected samples. The
histogram estimates voxel prevalence. It is not a histogram of the proposal,
coarse pyramid, selected nuclei, or inferred biological foreground.

## 4. A separate upper-limit policy for sparse highlights

`upper_policy="percentile"` uses the weighted lower and upper quantiles, by
default 0.01 and 0.995. That target can be estimated accurately while still being
visually poor when a clean bright feature occupies much less than 0.5% of voxels.

The default `upper_policy="highlight"` retains the same lower limit L and sets

```
H_hat(v) = sum w_i * max(x_i - L, 0) * 1(x_i <= v)
           / sum w_i * max(x_i - L, 0)
U = max(quantile(F_hat, 0.995), quantile(H_hat, 0.995)) .
```

H estimates the distribution of *positive excess intensity mass*, not the
fraction of positive pixels or probability of a biological label. Arithmetic is
scaled before subtraction to avoid intermediate overflow. The ordinary histogram
always continues to use F, not these highlight-policy weights.

This explicitly penalizes clipping a substantial fraction of observed intensity
mass even when the responsible pixels are rare. It is our engineering heuristic,
not a literature-established universal microscopy optimum. A sufficiently bright
hot pixel can still drive U upward and darken other structures. We do not silently
remove that observation as an outlier: we warn when fewer than four distinct
sampled tiles support the upper tail. Users can choose percentile policy, inspect
the histogram, increase the fixed budget, or choose their own window.

Constants, zeros and nonfinite-only samples have explicit fallbacks. No finite
samples means no suggested window. The library never manufactures a positive-cell
population or claims to distinguish a rare organelle from a detector defect.

## 5. What the uncertainty numbers mean

The estimator resamples complete **draw occurrences** with multinomial bootstrap
counts, keeping the frozen guide and its probabilities fixed. It does not treat
all pixels in a tile as independent, nor collapse repeated draws into unique
tiles. It recalculates the same lower/upper display rule for each replicate.

Reported 95% intervals are approximate, pointwise, fixed-budget, conditional
bootstrap intervals. They are withheld when fewer than 16 draws, fewer than four
distinct upper-tail tiles, or fewer than 20 bootstrap replicates are available.
The default 48 replicates is a speed compromise; endpoint Monte Carlo error is
material. Publication-level evaluations should use many more replicates and
measure repeated-seed coverage rather than assuming nominal coverage.

These are not confidence sequences, calibrated simultaneous channel intervals,
probabilities that the window is visually correct, or bounds on unseen signal.
For a known set B of tiles, the conditional probability of missing it in m draws
is `(1 - sum_B q_j)^m`; an unknown rare object has no known B. No amount of
bootstrap replication recovers a bright object absent from both pilot and final
sample. Draw-weight ESS is a diagnostic, not an iid pixel sample count.

## 6. Work, memory, and interaction budgets

Defaults are per channel: 128 base draws, at most 131,072 base samples, at most
128 pilot reads and 262,144 pilot samples, 32-pixel base tiles, 128-pixel pilot
read regions, and 48 bootstrap replicates. Tight base budgets shrink the tile
size to retain independent draws. A small complete census uses the larger tiles
when possible. The result reports reads, returned samples, unique tiles,
Z/T coverage, native pilot level, finite fraction, elapsed wall time, warnings,
and configuration. Elapsed time includes pauses between cooperative steps.

These limits do not count actual encoded bytes, whole native chunks decoded,
metadata I/O, codec scratch, or every intermediate NumPy allocation. A tiny
regional request can cause a large source chunk to be fetched. No hard latency,
process-RSS, or remote bandwidth guarantee is made. A no-pyramid source may gain
little from the pilot; `survey_reads=0` gives the uniform baseline.

The viewer runs steps on its existing single display worker. Foreground
navigation/rendering takes priority between steps; no new pixel-reader thread
or required dependency is added. Finished histograms are retained in a 32 MiB
array-payload LRU, enlarged only to fit one explicitly larger configured
experiment. Eviction never resets display windows or restarts automatic sampling.
Opening an evicted histogram can repeat that channel's seeded experiment.

Manual edits outrank late automatic results. Selections pause work and defer
application. Source changes cancel old jobs between reads; retained owners survive
until in-flight work is joined. A paint callback only reads detached histogram
results. Dragging handles performs no new statistical sampling. Histogram cells
cannot be exported as image-coordinate selections.

Z/T handoffs keep the last completed glyph grid and its old label while the new
plane renders. The new label is published with its new frame; obsolete frames
are rejected, and failed plane reads restore the previous usable observation.
This fixes a deliberate blank-canvas transition, not native terminal tearing.

## 7. Relation to prior work and a publication evaluation plan

ImageJ already documents stack-wide histogram contrast and display-range sliders
[4]. QuPath explicitly separates display LUTs from measured pixels [5]. A 2025
QuPath issue documents excessive downsampling collapsing a fluorescence preview
to values 0 and 1 [6]. This is a motivation/example, not a statement that current
QuPath still has that bug. Stratified quantile allocation is also established [7].
This implementation is a defensive importance-sampling design, not that paper's
kernel estimator or a claim of optimal stratification.

The prospective contribution is the measured combination of multiresolution
localization, base-resolution probability sampling, sparse-highlight display
policy, useful diagnostics, and bounded interactive scheduling. A literature
search here is not an exhaustive novelty review. We should not call this the
fastest contrast estimator or a publication-ready validated method yet.

A defensible evaluation should prerecord datasets, budgets, seeds and endpoints:
compare first-plane preview percentiles, coarse-only histograms, uniform base
sampling, and this guided estimator at equal read/sample budgets. Include full
small-array truth and independent exhaustive regional scans of manageable real
stacks. Vary rare-feature abundance/brightness, diffuse background, noise,
hot-pixel contamination, nonfinite values, isolated bright times/depths, chunk
layouts, and mean/nearest/XYZ pyramids. Hold out images when tuning defaults.

Measure CDF/quantile error, actual base-pixel clipping, excess-mass clipping,
rare-feature misses, repeated-seed variability and interval coverage. Visual
usefulness needs its own blinded assessment or predeclared task endpoint. For
speed, separately report first-image latency, estimate latency, metadata calls,
regional calls, actual chunk fetch/decode counts, transferred bytes, peak memory,
and cold/warm local/HTTP/S3 conditions. Pyramid construction is not free: report
it separately when pyramids were not already available.

`examples/benchmark_contrast.py` runs fixed-seed guided/uniform estimates on an
explicit source, reports work and timing, and optionally performs a capped
exhaustive scan. It is a reproducible starting point, not a finished comparative
study. Unit tests establish the implemented sampling identities, numerical
contracts, and UI behavior; they cannot establish cross-dataset superiority.

## References

1. Hesterberg T. (1995). *Weighted Average Importance Sampling and Defensive
   Mixture Distributions*. Technometrics 37(2), 185-194.
   DOI: https://doi.org/10.1080/00401706.1995.10484303
   Author's earlier report: https://statistics.stanford.edu/technical-reports/weighted-average-importance-sampling-and-defensive-mixture-distributions
2. Owen A. and Zhou Y. (2000). *Safe and Effective Importance Sampling*.
   JASA 95(449), 135-143. https://doi.org/10.1080/01621459.2000.10473909
   Related foundation; this patch does not implement its control-variate method.
3. Schulze Waltrup L. and Kauermann G. (2016). *A short note on quantile and
   expectile estimation in unequal probability samples*. Survey Methodology.
   https://www150.statcan.gc.ca/n1/pub/12-001-x/2016001/article/14545/02-eng.htm
4. ImageJ User Guide, Image > Adjust, stack histograms and display ranges.
   https://imagej.net/ij/docs/guide/146-28.html
5. QuPath documentation, Images: pixel values versus display LUTs.
   https://qupath.readthedocs.io/en/stable/docs/concepts/images.html
6. QuPath issue 1958, opened July 29, 2025: lowest-resolution contrast limitations.
   https://github.com/qupath/qupath/issues/1958
7. Eftekharian A. and Samawi H. (2021). *On kernel-based quantile estimation using
   different stratified sampling schemes with optimal allocation*. Journal of
   Statistical Computation and Simulation 91(5), 1040-1056.
   https://doi.org/10.1080/00949655.2020.1839900
