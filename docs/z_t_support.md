# Depth and time navigation

This branch targets twhy `35a38c8` and Omeify `74bf991`. Omeify owns storage,
axes, geometry and caches; twhy owns navigation and terminal presentation.

## Installation for this development branch

Install both local checkouts into the same Python environment. The Omeify checkout
must contain the tested `z_t_support` implementation, not just an older package
that happens to report version 0.22.2. No Java or additional runtime is added.

```bash
python -m pip install -e /path/to/omeify
python -m pip install -e '.[dev]'
python -m pip check
python -c 'import omeify; print(omeify.__file__); print(omeify.open_dataset)'
```

The paths above are explicit placeholders. This twhy branch raises its declared
Omeify minimum to 0.22.2, including the optional S3 extra. Update the dependency
floor to the actual release containing these interfaces before publishing twhy.

## Controls

| Control | Behavior |
|---|---|
| `d` | Cycle available dimensions: Z, T, Series |
| Click Z / T / S in the navigation bar | Choose that dimension; `*` marks the active one |
| `[` / `]` | Step backward / forward on the chosen dimension |
| PageUp / PageDown | Same on the canvas; with channel-list focus, keep channel paging |
| `p`, index, Enter | Jump within the active dimension; Escape cancels |
| Wheel, arrows, `+` / `-` | Existing zoom and pan; the wheel does not scrub Z/T |

Z, T and series indices are zero-based. A displayed `Z 4/8` means index four,
last index eight, nine planes total. PDF pages remain one-based and retain their
existing navigation and refinement. Singleton/absent axes have no scrubbing
control. Z is active initially when it has multiple sections; otherwise T,
otherwise Series. Index limits never wrap.

Opening an OME image without indices starts each present Z/T axis at zero:

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
meaning: fit a new image, reset its channels, and start its Z/T axes at zero.
Startup indices are not reapplied to every series.

Selection freezes one camera and one plane. It does not span Z/T coordinates.
GeoJSON stays anonymous and contains no source, series or Z/T metadata. Record
the displayed indices separately and choose that same plane when cropping or
analyzing the source. No animation, volume projection or 3D annotation is added.

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
Omeify speculative prefetch is not enabled in this first integration.

Series-count discovery uses one separate public Omeify metadata inspection at
startup because ImageDataset currently lacks collection descriptors. It reads no
pixels, but can repeat metadata requests. It is not repeated on Z/T changes.

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
