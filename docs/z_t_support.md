# Depth and time navigation

The initial Z/T implementation targeted twhy `35a38c8` and Omeify `74bf991`.
The contrast/histogram refinement targets twhy `f8f0ece` and Omeify `6e926f2` (0.23.0). Omeify owns storage,
axes, geometry and caches; twhy owns navigation and terminal presentation.

## Installation

Z/T support is included in the published **Omeify 0.23.1+**. Install twhy from
this checkout to test its 0.3.0 functionality before publication; pip resolves
the compatible Omeify release automatically. No Java or extra runtime is needed.

```bash
python -m pip install -e '.[dev]'
python -m pip check
python -c 'import omeify; print(omeify.__version__); print(omeify.open_dataset)'
python -m pytest -q tests/test_zt*.py tests/test_playback*.py tests/test_contrast*.py
```

The minimum is the same for the plain installation and the optional S3 extra.
Historical source commits above describe development provenance, not installation
requirements. Validate the installed Omeify distribution in the complete test
suite before publishing twhy.

## Controls

| Control | Behavior |
|---|---|
| `d` | Cycle available dimensions: Z, T, Series |
| Click Z / T / S in the navigation bar | Choose that dimension; `*` marks the active one |
| `[` / `]` | Step backward / forward on the chosen dimension |
| PageUp / PageDown | Same on the canvas; with channel-list focus, keep channel paging |
| `p`, index, Enter | Jump within the active dimension; Escape cancels |
| Wheel, arrows, `+` / `-` | Existing zoom and pan; the wheel does not scrub Z/T |
| `P` / playback chip | Start or pause a looping T slideshow; animated GIFs loop on opening |
| `R` / rate chip | Enter a slideshow rate from 0.1 to 30 fps |

Z, T and series indices are zero-based. A displayed `Z 4/8` means index four,
last index eight, nine planes total. PDF pages remain one-based and retain their
existing navigation and refinement. Singleton/absent axes have no scrubbing
control. Z is active initially when it has multiple sections; otherwise T,
otherwise Series. Index limits never wrap when stepping manually. Playback wraps T and animated GIF frames,
but never skips time points merely to catch up with the clock.

Opening an OME image without indices starts at middle Z (`size // 2`) and T=0:

```bash
twhy stack.ome.tif
twhy stack.ome.tif --z-index 4 --t-index 2
twhy experiment.zarr --z-index 4 --t-index 2
twhy experiment.zarr --z-index 4 --t-index 2 --snapshot --ansi -o plane.ansi
```

Explicit invalid indices fail, including an index supplied for an absent axis.
`--group` stays Zarr-only. Z/T arguments do not apply to SVS, raster frames or PDF.
The Python `open_image()` helper remains strict by default; pass explicit indices,
or opt into its documented `first_plane=True` frontend default.

Z/T changes preserve the camera, selected/focused channels, pseudocolors, contrast
windows, gamma and rendering style. Contrast is not recomputed on every plane;
press `a` to request that deliberately. A series change retains its previous
meaning: fit a new image, reset its channels, and start at its middle Z and T=0.
Startup indices are not reapplied to every series.

Selection freezes one camera and one plane. It does not span Z/T coordinates.
GeoJSON stays anonymous and contains no source, series or Z/T metadata. Record
the displayed indices separately and choose that same plane when cropping or
analyzing the source. No volume projection or 3D annotation is added.

## Pyramids, resources and responsiveness

Every displayed plane is an ordinary immutable Omeify Image. Automatic zoom uses
its exact-section-compatible XY pyramid. A native XYZ level that reduces Z is
not silently shown as the original optical section. The base and any compatible
XY levels remain usable; large exact sections without a cheap XY overview can
use the existing clearly labelled bounded sampled/runtime display overviews.
There is no automatic coarse-volume substitution in this implementation.

One dataset session stays open across Z/T changes. Its decoded TIFF segments or
Zarr chunks remain reusable across channels and depth/time positions. twhy no
longer clears the source cache on ordinary channel/level switches. Display preview
and overview caches are separate, plane-local ViewSession data. They are released
on plane handoff, preventing old pixels from being reused under a new plane label.

Rapid keys replace a single pending destination, not an unbounded queue. A
completed old load/frame is discarded. The old displayed plane retains its own
label while loading, then handoff occurs between reads. Quitting joins outstanding
work before closing sources. Native codec/network work cannot be forcibly
interrupted; no guaranteed navigation latency or process-wide RAM cap is claimed.

Routine Z/T changes do not print transient opening/rendering/completion messages.
A five-cell activity slot at the top right carries a small three-dot pulse while
work is pending. It never changes the title width or submits image reads. In
full-terminal mode it temporarily overlays the corner, without resizing the
canvas, then disappears. The last completed grid and its Z/T labels remain paired
until the next frame is ready. Errors remain explicit in the navigation/footer.
Omeify speculative prefetch is not enabled in this first integration.

Series-count discovery uses one separate public Omeify metadata inspection at
startup because ImageDataset currently lacks collection descriptors. It reads no
pixels, but can repeat metadata requests. It is not repeated on Z/T changes.


## Time-series slideshow and animated GIFs

**OME-TIFF and OME-Zarr:** An image with more than one time point opens paused.
**P** plays/pauses the T dimension, leaving Z, camera, channels, contrast,
gamma and rendering mode unchanged. The default is a **2 fps slideshow**, not a
claim to reproduce acquisition time. `--play-fps 3` or **R** chooses 0.1..30
requested frames per second. `--autoplay` opts into starting immediately.

**Animated GIF:** A GIF with multiple frames opens playing and loops, using its
per-frame encoded delays by default. **P** pauses; brackets/PageUp/PageDown
step frames; **p** jumps to a zero-based frame, and manual navigation pauses
playback. `--frame N` selects the opening frame. `--no-autoplay` starts paused.
**R** or `--play-fps 5` overrides the encoded delays with a constant slideshow
rate. Zero/sub-40-ms GIF delays are presented with a 40-ms minimum to avoid
unsafe busy loops. The loop is intentional even if the GIF declares a finite
repeat count. Static GIFs, APNG and animated WebP retain ordinary fixed-frame
viewing in this implementation. Snapshots always render just one frame.

Playback is **presentation-paced**: twhy shows each next completed frame, holds
the previous frame and its label through decoding/rendering, and starts the
following dwell interval only after publication. If a decoder or remote source
is slower than the requested rate, observed playback slows without skipping
frames or queueing an unbounded backlog. Mouse click-and-drag panning can span
frame changes without stopping playback or resetting the drag anchor; a new
series or changed image geometry still ends the gesture. Actual observed FPS
is therefore not guaranteed. No timestamps are invented for OME time points
or compared to wall-clock acquisition time. A failed read pauses playback and preserves the
last usable view. Selection, histogram mode, editing a playback rate, or explicit
navigation also pauses playback.

GIF decoding uses one Pillow GIF reader, respecting disposal/transparency and
compositing through Pillow, not a homegrown GIF codec. Immutable RGB display
pyramids are retained under a **64 MiB LRU byte budget**, with at most one
next-frame preparation queued using the existing source-loader executor. The
active frame and transient Pillow decoding/pyramid scratch are additional RAM.
Evicted frames are lazily decoded again. Omeify's existing TIFF/Zarr source cache
remains separate and persistent throughout T navigation; there is no second
OME decoder or T-volume memory cache.

**Continuous OME playback performance:** While a T slideshow is playing, the
idle render worker does not build whole-frame overviews of timepoints that
will be discarded on the next transition. This prevents extra native reads
from competing with the next requested frame. Normal paused browsing and
manual Z/T navigation retain idle overview preparation, and pausing playback
wakes the worker to resume it. There is no new decoder thread, prefetch queue,
cache enlargement, or frame skipping. Omeify's existing optional prefetch
is deliberately not activated: its shared 64 MiB native cache can fill with
demanded blocks, after which speculative blocks are not admitted. Increasing
thread count without addressing cache residency would add work, not fix a
throughput cliff.

To isolate slow source reads from resampling and text rendering on an actual
stack, run this no-terminal probe in the matching twhy/Omeify environment:

```bash
python examples/benchmark_time_playback.py ~/Downloads/00001_01.ome.tiff \
  --columns 100 --rows 30 > ~/Scratch/Test/twhy-zt/frame-timings.csv
```

The CSV has per-T setup, sampling and rendering milliseconds and native-cache
hit/load/eviction counts. It omits terminal output, playback dwell, and idle
overview construction. If sampling costs climb after cache eviction, inspect
native TIFF chunk/strip layout; if only the live terminal slows, investigate
terminal repaint and output throughput. A headless probe does not certify
sustained interactive FPS. Compare matching terminal dimensions and renderer.

## Deterministic local examples

```bash
python examples/make_zt_demo.py --output-directory ~/Scratch/twhy-zt-demo
twhy ~/Scratch/twhy-zt-demo/time-depth.ome.tif --channel 0 --channel 1
twhy ~/Scratch/twhy-zt-demo/time-depth-xy.zarr --channel 0 --channel 1
twhy ~/Scratch/twhy-zt-demo/time-depth-xyz.zarr --channel 0 --channel 1
```

The generator creates four time points, nine sections and two channels with
moving discs/rings. It verifies every small base plane through Omeify after
writing. The TIFF/XY-Zarr products have exact-section XY reductions; XYZ-Zarr
exercises the rule excluding Z-reduced levels from an exact optical section.
The destination products must not already exist. This is a synthetic test pattern,
not a biological simulation. Ordinary codecs, Zarr and `ome-schema` are required.

## Public examples discussed during planning

The [IDR OME-NGFF sample catalog](https://idr.github.io/ome-ngff-samples/) lists
these CC BY 4.0 examples. Dimensions below are catalog declarations, not a claim
that this patch has completed live remote chunk reads from those endpoints.
Public endpoints can change independently of twhy.

| Catalog image | Purpose | X/Y; C/Z/T |
|---|---|---|
| `idr0052A/5514375.zarr`, NGFF 0.4 | Small combined depth/time test | 256/256; 3/31/40 |
| `idr0062A/6001240.zarr`, NGFF 0.4 | Deep stack without a time series | 271/275; 2/236/1 |
| `idr0026/3.66.9-6.141020_15-41-29.00.ome.zarr`, NGFF 0.5 | Newer metadata plus declared collection layout | 507/507; 3/21/47 |

```bash
twhy 'https://livingobjects.ebi.ac.uk/idr/zarr/v0.4/idr0052A/5514375.zarr' \
  --z-index 15 --t-index 12

twhy 'https://livingobjects.ebi.ac.uk/idr/zarr/v0.4/idr0062A/6001240.zarr' \
  --z-index 118

twhy 'https://livingobjects.ebi.ac.uk/idr/zarr/v0.5/idr0026/3.66.9-6.141020_15-41-29.00.ome.zarr' \
  --series 0 --z-index 10 --t-index 12
```

Public input tests remain manual, not an automatic network dependency of pytest.
For each, zoom in, change Z/T and return, verify the field and contrast stay fixed,
try a range endpoint and an invalid jump, then repeat with the sidebar hidden and
with a frozen selection. Compare an explicit-plane snapshot. Remote TIFF remains
a bounded whole-file download before local regional reads, unlike native Zarr.

## Regression checks

```bash
python -m pytest -q tests/test_zt*.py
python -m pytest -q
python -m ruff check .
python -m build
```

New tests cover independently written TIFFs, all six T/C/Z storage orders, RGB,
Z-only/T-only/combined inputs, actual prompt_toolkit keyboard/mouse navigation,
load coalescing, source ownership, stale frames, failed loads, selection freezing,
CLI snapshots and POSIX terminal restoration. Real Zarr tests cover 0.4/0.5/0.6,
permuted axes, mixed XY/XYZ pyramids, shared chunks, sharding and loopback HTTP.
Those Zarr tests intentionally fail rather than silently skip when a required
backend is missing. See `docs/validation.md` for what was actually executed.

## Stable contrast and uninterrupted presentation

For OME-TIFF and OME-Zarr intensity sources, including ordinary 2D images,
a bounded base-pixel-guided estimate runs **before the first frame**, when fast
enough. Otherwise the initial preview estimate is retained. In neither case
does a later background computation silently change the displayed limits.
Z/T navigation does not recalculate contrast; manual and explicit startup limits
are preserved. `--no-stack-contrast` disables the initial sampling work. H/A
request detailed histograms and explicit rewindowing on demand. See
[the method and histogram controls](contrast-estimation.md).

The last completed character grid and its matching Z/T label remain visible
while another section is rendered. Successful pixels and their label are
published together. Obsolete results cannot replace newer requests. A failed
new-plane read restores the previous usable source instead of blanking it.
This concerns application presentation, not a guarantee about terminal repaint
tearing. The source's raw values and pyramid semantics do not change.
