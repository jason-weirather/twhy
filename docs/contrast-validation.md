# Contrast/histogram refinement: validation record

## Exact inputs and scope

- twhy `f8f0ece3e70199f87afe609fcd2b11e7060deed3`, branch `t_z_support`, v0.3.0.
- Omeify `6e926f255c7864eeb892c9d1a58f017e72534573`, branch `z_t_support`, v0.23.0.
- Reconstructed all 83 included twhy text files and 188 Omeify files from their
  supplied snapshots, verifying each advertised byte count. The snapshot omitted
  ten existing twhy media files; no edits depend on those omitted files.
- No Omeify runtime, schema, dependency, or documentation changes are included.
- No new runtime dependency or package-version bump is introduced. The optional
  S3 requirement is aligned with the existing plain `omeify>=0.23.0` requirement.

## What was implemented

The public estimator consumes an already-open Image or ImageDataset. It performs
an optional frozen low-resolution pilot, then full-support, with-replacement
importance sampling of base-resolution tile clusters. It returns a weighted CDF,
histogram, an explicitly separate highlight/percentile display recommendation,
coverage and work records, and qualified tile-bootstrap intervals. Small data
that fit both budgets are enumerated exactly. The methods document specifies
formulas, numerical behavior, source lifetime, costs and limitations.

H/A/L and draggable ^L/^U provide the same capability in the existing terminal
canvas. Histogram focus does not toggle channel visibility, and mouse adjustments
reuse the sampled distribution without new I/O. Manual numeric/gamma/preview
adjustments override queued and running automatic applications. Scalar stack
startup receives one incremental estimate per selected channel; Z/T changes do
not recalculate it. Explicit startup windows are protected. RGB retains its native
unsigned display range. Ordinary 2D/snapshot contrast stays unchanged.

Omitted startup depth now uses size//2 and time uses zero. Explicit indices retain
priority. Plane transitions retain the old completed character grid and label
until replacement pixels are ready; failures restore the old usable observation.

## Executed test results

Environment: Linux, Python 3.13.5, NumPy 2.3.5, SciPy 1.17.0, tifffile 2026.5.15,
Pillow 12.3.0, pypdfium2 5.8.0, prompt_toolkit 3.0.52, pytest 9.0.2,
pytest-asyncio 1.3.0, setuptools 82.0.1. Required dependencies `zarr`,
`imagecodecs`, `ome-schema`, and `coolname` are unavailable here. Attempts to
install them failed because package-download DNS/network access was unavailable.
No fake decoder, model, schema validator, or naming package was substituted.

**Complete attempted run: 688 passed, 65 failed, 1 skipped, 19 warnings.**

The untouched input snapshot, in the same environment, produced **629 passed,
60 failed, 1 skipped, 19 warnings**. Comparing failure IDs gives:

- 38 existing naming/selection/terminal failures without `coolname`, reproduced
  on the untouched snapshot.
- 20 existing Zarr tests fail at the missing Zarr dependency.
- One existing public demo test stops at missing `ome-schema`.
- Six new required NGFF contrast tests stop at missing Zarr.
- One baseline packaging assertion expected 0.22.2 despite the supplied project
  already requiring 0.23.0. Its expectation and the optional S3 floor are fixed.

There are no additional failing test IDs beyond the six missing-Zarr integration
cases. This does not establish that the dependency-blocked paths will pass once
installed. The new real Zarr cases remain required tests, not passing skips.

A separate run with exactly those 65 dependency-blocked test IDs deselected
completed: **688 passed, 1 skipped, 65 deselected, 16 warnings**. The one skip is
the existing real-coolname vocabulary check. Warnings come from the Python 3.13
PTY harness using forkpty from a multithreaded test process.

The 58 executable new tests cover weighted empirical CDF/quantile contracts,
unequal edge-tile probabilities, defensive-mixture normalization and HH totals,
repeated-seed targeting-bias comparisons, clustered bootstrap behavior, sparse
bright signals, constants, NaN/Inf values, RGB/labels, reproducible budgets,
source lifetimes, independent XY/XYZ guide fixtures, actual TIFF readback,
no pilot-value contamination, and JSON/output ownership.

Real prompt_toolkit tests cover H/A/L, actual SGR mouse bytes, caret dragging,
limit-crossing protection, channel focus, resize, explicit/manual window priority,
queued as well as in-flight automatic work, source changes while editing, cache
payload eviction without range resets, histogram Z/T/series navigation, stale
frame rejection, failed-plane rollback, and shutdown joining a contrast read.

Existing Z/T tests were updated for intentional middle-Z defaults, not relaxed
for incorrect pixels. One PTY test now waits for an actual stable redraw rather
than a transient status message or full text that a terminal diff need not resend.

## Synthetic accuracy and timing experiment

A separate reproducible experiment constructs 33,554,432 uint16 voxels:
4T x 8Z x 1024Y x 1024X. Background is 0..100. A single 128x128 bright region at
one T/Z position occupies 0.048828125% of the population. An independently
constructed 16x XY mean pyramid is already available. This is an **in-memory
provider**, not a TIFF, Zarr, network, cold-disk or production-slide benchmark.
Pyramid construction is excluded from estimator timings.

A complete independent integer histogram gives lower=1, ordinary 99.5th
percentile=100, and the full-population highlight-policy upper=23,744.
Across ten fixed seeds:

| Method | Returned samples incl. pilot | Median seconds | Rare region detected | Estimated upper range |
|---|---:|---:|---:|---:|
| Guided, 128 base draws | 262,144 | 0.1504 | 10/10 | 23,518..23,831 |
| Uniform, 128 base draws | 131,072 | 0.1262 | 0/10 | 100..100 |
| Uniform, 256 base draws | 262,144 | 0.2792 | 0/10 | 100..100 |

The guided run returns 0.78125% as many samples as the base population, including
pilot values. Its 160 regional reads are 32 pilot reads and 128 base reads. The
uniform equal-returned-sample comparison uses 256 base reads, so it is not an
equal-request or equal-byte-transfer experiment. The complete integer histogram
scan took about 0.759 seconds in one run; this is a different, exhaustive algorithm,
not a controlled end-to-end comparison with full viewer startup.

All ten guided conditional upper intervals contained this fixture's complete
highlight cutoff. All ten uniform intervals missed it because their samples never
encountered the rare region. This is an important counterexample to interpreting
bootstrap precision as a guarantee of rare-feature detection. The implementation
always warns about unseen rare signal on sampled runs. Ten seeds on one designed
fixture do not establish calibrated coverage or general superiority.

## Visual and packaging checks

Actual prompt_toolkit screen characters/styles were captured at 100x30 and 60x24
terminal cells, with an additional monochrome ASCII capture. The resulting PNGs
are reconstructions of those real grids, not generated UI mockups or native macOS
screenshots. Carets, metadata text, focus and bars were visually inspected. Local
font files are not included in any deliverable.

83 Python source/test/example files parse with Python 3.11 grammar. This is not
an executed Python 3.11 runtime test. Ruff is unavailable and is not claimed to
pass. Basic whitespace and source syntax checks pass.

Wheel and source distribution builds succeed using the installed setuptools
backend. The wheel includes all new runtime modules; the source distribution
includes the methods guide and benchmark example. A wheel installed outside the
checkout performed an exact TIFF-stack census, JSON serialization, text histogram
rendering, and an ordinary CLI TIFF snapshot using the real Omeify source.
This is not a fresh dependency resolver or PyPI-wheel interoperability check.

## Remaining gates

Run the full suite with all declared dependencies, including the six real NGFF
contrast cases. Validate the minimum Python runtime and Ruff separately. Exercise
local and remote public stacks, especially rare markers, isolated bright time
points, hot pixels, unknown pyramid geometry, and oversized native chunks.
Measure first-frame/estimate latency and actual transferred/decoded bytes rather
than inferring storage performance from returned sample counts. No native macOS,
Windows, live S3, or public IDR benchmark was executed here.

The display policy is useful engineering, not a validated biological foreground
model. The statistical design and diagnostic warnings are documented; novelty,
optimality, cross-dataset speed advantages and publication-level interval coverage
are not established by this patch.
