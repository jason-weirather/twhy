# twhy 0.2: Omeify 0.18 migration validation

This update targets the supplied `2269e1c1db738e83e36ab9a120980dd61ed3ef9e`
snapshot. It replaces the old file-only adapter with a ViewSession borrowing an
ordinary Omeify Image. No second TIFF decoder or pixel-normalization path is added.

## Executed checks

**108 tests passed** against the actual Omeify 0.18 source reconstructed from the
provided snapshot and consolidation patch. These include independent TIFF
fixtures, numerical rendering, Click snapshots, the actual prompt_toolkit viewer,
and two POSIX pseudo-terminal tests. Two Python 3.13 forkpty deprecation warnings
came from the terminal harness; neither was a test failure.

The replaced file-adapter tests were consolidated around current behavior:
file/array equivalence, regional reads without whole-level materialization,
RGB logical-channel semantics, uint32 display precision, explicit dtype/byte
order handling, anisotropy, fractional viewports, empty coverage, current read
budgets, cache eviction, source failure, and source close/reopen invalidation.
A huge procedural image is described without allocating its complete raster.
Its requested channels and absolute-coordinate values are checked independently.

Declared pyramid scales and odd-sized boundary coverage have dedicated numerical
checks. Unknown scales retain a visibly labelled extent-fit display approximation;
this is not inferred physical calibration. Categorical LabelImages are explicitly
rejected because object-ID brightness would not be categorical visualization.

Against the untouched twhy/Omeify 0.16.1 baseline, CLI help and four real snapshot
workflows matched byte-for-byte in stdout and stderr: grayscale ASCII,
multichannel ANSI, RGB half-blocks, and a read-budget-limited crop. Those fixtures
have declared scales and dimensions divisible through their pyramids. This does
not claim that corrected odd-sized mapping or newly labelled unknown scales
produce unchanged text.

Actual Mocktome mIF and H&E image handles were sampled and rendered without an
intermediate TIFF. The exact upper/lower half-block color arrays were inspected
as enlarged PNGs; these are representations of TextImage cells, not screenshots
of a terminal emulator. The same open mIF image passed through Tilework 0.9 and
Cadastre 0.15, with no input TIFF staged. Cadastre used a small CPU test segmenter,
not Mesmer or StarDist.

## Packaging and environment

Python 3.13.5 on Linux; NumPy 2.3.5, SciPy 1.17.0, tifffile 2026.5.15,
prompt_toolkit 3.0.52, and pytest 9.0.2. The complete real dependency source was
used; the Image contract and TIFF reader were not replaced by mocks.

Wheel and source-distribution construction uses the installed setuptools build
backend. No font, external image, model weight, or simulator source is bundled.
The pure-array renderer remains importable without importing Omeify or the
terminal frontend. The package retains its Python 3.13 minimum.

## Limits

Ruff and the `build` command-line frontend were unavailable. The local OME XSD
and imagecodecs were also unavailable. Viewer tests write TIFF fixtures
independently and do not require an OME writer-validation bypass. Deflate and
uncompressed reads were exercised; JPEG/JPEG 2000/LZW codecs were not.

No real patient slide, multi-gigabyte production slide, cluster deployment,
macOS/Windows terminal, or actual SSH/tmux combination was tested. Source-sample
and preview-cache budgets are not a process-RSS limit. A generic provider can
perform expensive work internally, and decoded caching remains provider-owned.
This is not a color-managed or diagnostic microscopy display.

## Omeify 0.21.0 / Python 3.11 baseline (October 2026)

The preceding validation record describes the historical Omeify 0.18 migration and
its then-current Python 3.13 minimum. The packaging baseline is now
`omeify>=0.21.0` and `requires-python = ">=3.11"`; the default Conda environment
uses Python 3.11. No image sampling, rendering, or terminal interaction logic was
changed for this transition. In particular, twhy still consumes Omeify's public
`Image` and `OMETiffReader` APIs, without a second TIFF decoder.

The complete twhy test suite was run against the **Omeify 0.21.0 source snapshot**
(commit `6d9f5ff`) under Python 3.13.5: **108 passed, 2 warnings**. All twhy
source, demo, and test modules also parse with Python 3.11 grammar. This is a
source-level integration test, not verification of the separately published PyPI
wheel or an executed Python 3.11 runtime test. A Python 3.11 interpreter was not
available in the test environment.

To validate the newly supported interpreter using the published dependency:

```bash
mamba env create -f environment.yml
mamba activate twhy_env
python -m pip install -e '.[dev]'
python -m pip check
python -c 'import sys, omeify; print(sys.version); print(omeify.__version__)'
python -m pytest -q
```

Also smoke-test a real RGB and multiplex OME-TIFF, especially when the downstream
TIFF codec and terminal combination differs from the synthetic fixtures. Python
3.11 compatibility should not be called fully verified until this lane passes.

## Foreground-only terminal render modes (October 2026)

This patch targets the supplied twhy `aed55e5` snapshot. It adds default `detail`,
artistic `shape`, and legacy `simple` modes; `ascii` remains an alias for simple
and the original `blocks` renderer remains available. No dependency or Python
minimum was added/raised; the package version is unchanged at 0.2.0.

### Executed checks for this patch

**163 tests passed**, with **94% reported statement coverage**, on Linux with
Python 3.13.5 and the actual reconstructed Omeify 0.21.0 source (`6d9f5ff`). NumPy
2.3.5, SciPy 1.17.0, tifffile 2026.5.15, prompt_toolkit 3.0.52, and pytest 9.0.2
were used. Four `forkpty` deprecation warnings came from the POSIX terminal tests.
They were not failures. This is not a separately installed PyPI-wheel test.

The checks include all 256 Braille patterns against independent literal dot
positions; within-cell geometry that has the same mean but different orientation;
foreground-only and plain-text output; NaN/partial coverage; deterministic batch
matching; richer source sampling; retained read/cache budgets; source lifetimes;
mode cycling; locked windows; monochrome/blocks round-trips; custom legacy ramps;
and actual keyboard, mouse, resize, and terminal-restoration behavior. All three
text modes were opened and interrupted through real POSIX pseudo-terminals.

Eight byte-level goldens were captured from the untouched aed55e5 renderer across
grayscale/RGB, color/no-color, and inversion settings. Simple matches them exactly.
Four complete old/new CLI workflows also had identical stdout and stderr when
the new invocation selected the equivalent legacy mode: grayscale snapshot,
multichannel ANSI snapshot, RGB half-block snapshot, and read-budget-limited crop.

Wheel and source-distribution builds succeeded through the installed setuptools
backend. The wheel includes both new renderer modules and no font assets.
Pure-array rendering was checked without importing Omeify or prompt_toolkit.
All Python source, examples, and tests parse with Python 3.11 grammar.

### Visual inspection and performance scope

Actual `TextImage` results were inspected for the supplied reaction-image crop
(with its letterboxing removed) and deterministic synthetic brightfield, single
marker, and multichannel fields from `examples/make_demo.py`. The comparisons
used equal 80-column text budgets. Inspection images were rasterizations of actual
characters using local fonts, not generated UI mockups or patient-slide results.
Those local fonts are not bundled with twhy. Raw text and ANSI were also retained.

On a 512-by-512 synthetic RGB array rendered to 120 columns by 40 rows, median
render-only times over five warm runs were 5.4 ms for simple, 37.1 ms for shape,
and 35.6 ms for detail. These measurements include array resampling but exclude
TIFF decoding, terminal repaint, and SSH transport. They are not an interactive
frame-rate guarantee or a benchmark against other character-art packages.

### Remaining limits

A Python 3.11 interpreter could not be installed in this sandbox because network
DNS resolution failed. Actual Python 3.11 runtime validation therefore remains
outstanding; grammar checks are not a substitute. JPEG/LZW/production-slide and
real macOS/Windows/SSH/tmux validation were not performed in this pass.

Detail's dot-count fit is not a claim of perceptual optimality. Shape's geometric
stencils are not a measured terminal font. Artistic sharpening/relief can alter
appearance and must not be interpreted as segmentation or quantitative evidence.
The ordered pattern is deterministic but screen-grid anchored, so panning can
still change its texture. Both structured modes may need finer pyramid reads and
therefore a tighter initial crop under the same source-read budget.

## Auto terminal renderer selection (October 2026)

Against the supplied twhy `1679265` snapshot, this change makes **auto** the CLI
mode default without editing the original rendering algorithms. Interactive
truecolor/256-color Unicode terminals select blocks. Low-depth, dumb, or
unsupported-encoding terminals select simple. Explicit modes remain available;
`NO_COLOR` and prompt_toolkit's color-depth override are honored. Plain auto
snapshots select simple, while `--ansi` auto snapshots select blocks.

The selection is based on advertised terminal capabilities, not a font probe.
Quarter/block-character experiments remain future work. The Python library's
`TextRenderer()` default is still detail, unaffected by environment variables.

## Ordinary raster and optional PDF ingress (October 2026)

This patch targets the supplied twhy `aec704f348cfe2b8a418f627a14e3e1ddf11a819`
snapshot. Python >=3.11, Omeify >=0.21.0, package version 0.2.0, and all rendering
algorithms remain unchanged. Pillow is a new base dependency; the optional `pdf`
extra adds pypdfium2. Ordinary files enter through Omeify's public array-image API,
not an alternative ViewSession or TIFF decoder.

### Executed checks

**281 tests passed**: 271 non-PTY tests and 10 POSIX pseudo-terminal tests, with
**94% reported statement coverage** across the combined runs. This includes all
188 baseline tests. The 10 forkpty deprecation warnings came from the terminal
harness under Python 3.13; they were not failures. Coverage does not instrument
the separately spawned terminal subprocesses, which have their own output and
restoration assertions.

The test environment was Linux, Python 3.13.5, NumPy 2.3.5, SciPy 1.17.0,
Pillow 12.3.0, pypdfium2 5.8.0, and tifffile 2026.5.15. Integration used the actual
Omeify 0.21.0 source (`6d9f5ff`) reconstructed from its repository snapshot. It
was not replaced by mocked Image/TIFF implementations or a local API imitation.
This does not verify the separately published Omeify wheel.

New checks cover actual PNG, JPEG, WebP, BMP, GIF, ICO, PPM and TGA codecs;
GIF/APNG/WebP frame selection; palette, alpha and grayscale transparency;
bilevel, grayscale and CMYK display; EXIF orientation; scalar 16-bit PNG precision;
RGB logical-channel/window semantics; filename-independent dispatch; missing
PDF extras; invalid cross-kind options; input/hard-link overwrite protection;
Pillow's large-image guard; and rejection of unsupported inputs without external
converter execution. A roughly 3.8-megapixel RGB PNG fits using its RAM pyramid
under a 60,000-sample per-view budget, then returns exact base pixels on zoom.

Pyramid levels are compared independently with area means taken directly from
base-array rectangles across integer/float, odd, skinny and RGB shapes. Tests
explicitly check finite/missing samples, partial-edge weighting, unchanged base
pixels, immutable ownership, explicit dyadic scales, and nonaccumulating integer
rounding. TIFF inputs are checked not to call Pillow or construct RAM pyramids.

PDF fixtures are independently assembled vector documents with the standard
library, not written by the decoder under test. Tests exercise page selection,
rotation, opaque mattes, RGB rather than BGR, real rasterization at 72/144/300 DPI,
owned pixel lifetime after native handles close, malformed PDFs, invalid pages,
excessive native dimensions, and snapshots. Both PNG and PDF were driven through
the actual prompt_toolkit application and through real CLI pseudo-terminals,
including zoom/pan, contrast, automatic half-block selection, and restored
alternate-screen, mouse, and cursor state on exit.

Visual checks used a local sample photograph encoded as PNG/JPEG/WebP and placed
in a generated PDF page. The actual TextImage half-block foreground/background
colors were rasterized and inspected at a shared 100-column budget. These were
cell-color reconstructions, not screenshots of a physical terminal emulator.
The photograph, generated PDF, inspection images and local fonts are not included
in the patch or package.

### Scope and remaining checks

The full source and tests parse with Python 3.11 grammar. Wheel and sdist builds
were checked with the installed setuptools backend. The array renderer was
exercised under an import guard that prohibits file-decoder and terminal imports.
No converter executable, GUI, display server, GPU, or disk image cache is needed.

A Python 3.11 runtime, minimum-version Pillow/PDFium combinations, macOS/Windows
terminals, SSH/tmux combinations, large production slides, and every PDF feature
were not exercised. Ruff was unavailable in this environment. Pillow builds
without WebP support skip the WebP codec tests; this test environment supported
WebP and executed them. Optional PDF integration tests skip without `twhy[pdf]`;
they were installed and executed here. To run both lanes in a checkout:

```bash
python -m pip install -e '.[dev,pdf]'
python -m pytest --cov=twhy --cov-report=term-missing
ruff check .
python -m build
```

Pillow remains the ordinary image decoder, with its supported sample depths and
large-image protection. Higher-bit-depth RGB previews can be reduced to RGB8;
scalar 16-bit PNG keeps raw uint16. PDF pages are fixed-resolution raster previews,
not a text/search interface or unbounded vector zoom. Native PDFium calls within
twhy are serialized; direct PDFium use elsewhere in an embedding application
must coordinate separately. RAM storage follows Omeify's array ownership policy
and is not governed by the per-view source-sample budget.

## PDF page / OME series navigation and progressive detail (October 2026)

This patch targets the supplied `c43a5e18b66bd1e608c883f24308471a6fbc0cb0` snapshot.
No dependency, Python minimum, package version, or text-rendering algorithm changes.
The original 144-DPI/fixed-resolution validation above is historical; interactive
PDF viewing now refines up to `--pdf-max-dpi` (600 by default).

### Executed checks

**314 tests passed across the final split runs:** 302 non-PTY tests and 12 POSIX
pseudo-terminal tests. This includes the existing 281 tests, with CLI PDF-DPI
expectations updated for the intentional flag replacement. The non-PTY run reports
**92% statement coverage**. Coverage does not instrument spawned PDF or terminal
processes; their actual behavior has explicit integration assertions. The PTY tests
report Python 3.13 `forkpty` deprecation warnings, not application failures.

Environment: Linux, Python 3.13.5, NumPy 2.3.5, SciPy 1.17.0, Pillow 12.3.0,
pypdfium2 5.8.0, tifffile 2026.5.15, prompt_toolkit 3.0.52, pytest 9.0.2.
Tests use the actual Omeify 0.21.0 source (`6d9f5ff`), not an imitation of its API.
All reconstructed baseline twhy file byte sizes were checked against the supplied
snapshot. The patch is checked against a fresh baseline reconstruction. Wheel and
source-distribution builds succeed with the installed setuptools backend.

New checks exercise direct page/series entry, invalid destinations, cancellation,
PageUp/PageDown, bracket navigation, clickable navigation buttons, RGB/multichannel
series changes, and OME navigation with whole-image materialization prohibited.
Actual terminal subprocesses cover both PDF and OME destination entry, resize,
exit status, alternate-screen restoration, mouse state and cursor restoration.
The normal PDF terminal test quits with real refinement work outstanding.

Actual spawned PDF jobs test native rendering, RGB byte order, owned/read-only
pyramids, worker death, process cancellation, receiver cleanup and no image-cache
files. A real file-viewer test reaches 600 DPI, changes pages, rapidly retargets,
then quits and verifies that child processes are reaped. Controlled-completion
tests additionally exercise 600-before-300 results, current-page priority before
neighbor work, cached-page reuse, moving-cache eviction, released distant images,
coalesced source loads, and source handoffs while a display read is still running.

Fractional PDF page extents test page-relative camera preservation rather than an
assumed exact DPI ratio. Contrast survives upgrades. A custom read-budget test
verifies that automatic refinement cannot move the camera: a rejected upgrade
stays cached, then succeeds after a closer zoom. Snapshot coordinates are checked
against the same initial-preview grid. High-detail failures preserve a usable
lower-resolution source and display an error.

The terminal tests exposed a cancellation-lifetime race during development. The
final scheduler uses Python 3.11 TaskGroup to await every sibling finalizer. A
regression test deliberately delays one finalizer while the other finishes and
verifies that shutdown does not close the receivers early.

### Full-page and visual spot checks

One synthetic letter-size vector PDF was opened at 144 DPI, then rasterized at
300 and 600 DPI in parallel with the actual worker implementation. In this one
run, quick-preview rasterization/pyramid preparation took about 0.76 seconds;
refinement/transfer took about 3.24 and 3.84 seconds from submission, respectively.
These are environment- and workload-specific spot checks, not benchmark promises.

The resulting 600-DPI raster was 5100 by 6601 RGB pixels (PDFium rounds native
raster extents); its retained pyramid was about **128.4 MiB**. The largest child's
reported peak RSS was about **1097 MiB**, illustrating that construction and IPC
scratch are much larger than retained raster storage. This does not measure or
cap total process-tree RSS, and does not imply every PDF page is safe at 600 DPI.

Actual half-block output for the same close-up of six-point lettering and fine
vector lines at 144/600 DPI was rasterized and visually inspected. These were
reconstructions of TextImage foreground/background colors, not photographs or
screenshots of a physical terminal. Fixtures, inspection images and fonts are not
bundled in the patch or package.

### Remaining validation limits

Python 3.11 grammar checks pass; an actual Python 3.11 runtime was not available.
Native macOS/Windows terminals, SSH/tmux transport, minimum supported PDFium/Pillow
versions, large production OME series and complex real-world PDFs were not tested.
The standalone Ruff executable was unavailable. Snapshot and array-renderer
regressions, source lifetime tests and actual synthetic PDF/OME integrations were
run. No claim of diagnostic color management or unrestricted vector zoom is made.

## Rectangle selection, PDF text and clip delivery (October 2026)

This patch targets the supplied `1faa6c04ce11433736dff2e4678a0ca694338530`
snapshot. All 48 reconstructed baseline files matched their declared byte sizes.
The PDF default remains 600 DPI. Dependencies, Python minimum, package version,
image sampling/pyramid algorithms and normal rendering algorithms are unchanged.

### Executed checks

**394 tests passed across split runs: 380 non-PTY tests and 14 POSIX terminal
tests.** The final non-PTY run reports **92% statement coverage**. Tests include
all original 314 tests plus 80 new tests/parameterized cases. Terminal tests were
split into shorter invocations for the execution environment's command deadline;
coverage does not instrument the spawned terminal/PDF processes. Python 3.13's
forkpty warnings come from the multithreaded test harness, not application errors.

New checks exercise exact Unicode/space-preserving TextImage crops; immutable
foreground/background ownership; drag direction and inclusive endpoints; keyboard
anchors, Shift+arrows, corner swapping and clamping; border exclusion; actual
mouse/keyboard interaction; clickable buttons; Ctrl-C copy rather than quit in
selection mode; stable Save prompts; terminal resize invalidation; PDF refinement
handoffs deferred until selection ends; copied content pinned while an async save
runs; one outstanding clip operation; and immediate-quit save completion.

Independent two-page standard-font PDF fixtures cover 0/90/180/270-degree page
rotation, nonzero origins, fractional page dimensions, CropBox offsets and the
144/300/600 DPI coordinate grids. Rectangle extraction uses real PDFium, compared
with independently calculated coordinate transforms and literal expected words.
Tests verify page changes, missing text layers, explicit screen-glyph copying,
changed-on-disk rejection, and no extra raster/cache files during extraction.

File-delivery tests cover UTF-8/LF output, preserved rectangular spaces, atomic
replacement, no-overwrite, input and hard-link aliases, output symlinks, symlinked
directory components, nonregular files, missing directories, and rechecking a
destination that becomes an input symlink during publication. Clipboard tests
check exact base64 payloads, write-only OSC 52, byte limits without truncation,
helper selection and encoding, no shell evaluation, timeout fallback, remote/
multiplexer routing, and successful file saves despite clipboard failure.
The native-helper unit tests simulate process invocation; they do not change a
real macOS, Windows, X11 or Wayland clipboard.

Actual CLI PTY tests open PNG and PDF files, select and copy rectangles, decode
the emitted OSC 52 to compare the exact clip, verify explicit text and ANSI files,
and check clean exit/alternate-screen/mouse/cursor restoration. These prove emitted
protocol bytes and files, not acceptance by a particular desktop terminal.

### Existing shutdown race reproduced and fixed

The baseline non-PTY run reproduced a failure in the existing real PDF navigation/
rapid-quit test: a PDF process could remain tracked after its normal successful
cleanup was cancelled. TaskGroup alone did not prevent interruption inside an
awaited finalizer. This patch shields the entire process/pipe finalizer and waits
through repeated cancellation. A new actual-worker regression test cancels twice
while successful cleanup is deliberately paused, then verifies the child is reaped.
The existing real PDF navigation/rapid-quit test passes with this fix.

### Visual and packaging checks

A generated PDF page and the actual prompt_toolkit rendered screen were inspected
as PNGs. The screen inspection reconstructed the application's final character/
style grid using a local monospace font and exact half-block colors. The outline,
active corner, selection help and buttons were checked. Selecting the first text
region exported `ALPHA one` while excluding the other line and right-hand text.
This is a reconstruction of actual UI output, not a native terminal screenshot.
Fixtures, inspection PNGs and fonts are not bundled in the patch or package.

All 44 Python source/test/example modules pass Python 3.11 grammar parsing.
Wheel and source-distribution construction use the installed setuptools backend.
The final patch is also applied and tested against a fresh baseline reconstruction.

### Environment and limits

Linux/Python 3.13.5; NumPy 2.3.5, SciPy 1.17.0, Pillow 12.3.0, pypdfium2 5.8.0,
tifffile 2026.5.15, prompt_toolkit 3.0.52, pytest 9.0.2, setuptools 82.0.1.
Integration uses the actual Omeify 0.21.0 source from the available `6d9f5ff`
snapshot, not an imitation of its Image API. All reconstructed Omeify Python
source files used here matched their declared byte sizes; this does not verify
its separately published wheel.

An actual Python 3.11 runtime, minimum supported PDFium version, native desktop
clipboard, live SSH/tmux/Screen transport, and real macOS/Windows terminals were
not exercised. Ruff and the `build` CLI frontend were unavailable. No OCR or
layout-analysis capability is claimed. Invisible/badly encoded/OCR text layers
can differ from visible lettering; extraction preserves PDFium's text-layer order,
not a guaranteed visual reading order. OSC 52 remains terminal-policy-dependent
and unacknowledged; file saving is the portable explicit fallback.

## Shareable selected PNG for chat apps (October 2026)

This incremental patch applies after the rectangle-selection patch on `1faa6c0`.
It retains the viewer's PDF detail default of 600 DPI and adds no dependencies or
Python-version increase. PNG bytes are rendered from the frozen `TextImage`, not
from a new PDF/image raster read. In half-block mode every upper/lower half uses
the exact RGB foreground/background array values, without terminal fonts or
embedded ANSI escape codes. Braille dots are reconstructed geometrically;
other glyphs depend on available local fonts and can differ from terminal fonts.

**Executed validation:** 402 tests passed in five separate runs: 388 non-PTY
and 14 actual PTY tests. A combined one-process suite run exceeded the test
runner's timeout without an assertion failure; the five smaller runs cover
all 402 collected tests. Linux/Python 3.13.5, real Omeify 0.21.0 source,
Pillow 12.3.0, pypdfium2 5.8.0. The new tests check per-half pixel colors
in decoded PNGs, fixed cell geometry, Braille/ASCII visibility, export size
limits, atomic PNG save, input/hardlink protection, path collisions, local
clipboard-helper command payloads, explicit remote/OSC 52 failures, and keyboard
selection followed by image copy/save. Existing PDF navigation, all 14 terminal
PTY tests, and the original text/ANSI selection actions pass unchanged.

Local helper invocation on macOS, Wayland, and Windows was simulated; actual
macOS/Windows/Wayland/X11 image-paste acceptance by Discord has **not** been
measured. Native helpers are optional; unavailable/remote environments can
save PNGs explicitly. On macOS, the helper briefly uses a private temporary
PNG file for AppleScript clipboard ingestion and deletes it immediately. This
is not an intermediate image pyramid or persistent cache. On SSH/tmux, OSC 52
is text-only and no attempt is made to transmit PNG clipboard data through it.


## Anonymous multi-area selection, union export and channel paging (October 2026)

This patch targets the supplied `3d8ae2de8f4ac0ba983d85616698053b6465e67d`
snapshot. All 57 reconstructed files matched their declared byte sizes and final
newline flags. Python >=3.11, version 0.2.0, PDF's 600-DPI default, and the existing
rendering/sampling algorithms are unchanged. `coolname>=2.2,<6` is the sole new
runtime dependency; UUIDv4 comes from the standard library.

### Executed checks and naming-library limitation

**427 non-PTY tests passed, one skipped**, with **91% statement coverage**.
**15 POSIX pseudo-terminal tests passed** in two separate lanes, including the
new mixed rectangle/polygon export workflow. The combined result is **442 passed,
one skipped**. All image, Omeify, PDFium, NumPy, prompt_toolkit and subprocess
behavior used real implementations, except for explicitly identified unit-test
spies and controlled-completion test fixtures.

**The real coolname distribution could not be installed in this sandbox because
package-download/network access failed.** The naming adapter was checked against
the documented `generate_slug(3)` API, and a spy asserts that exact call. The
real-package vocabulary smoke test is the one skipped test. Integration tests
used a clearly separate, temporary deterministic word-generator double, including
an isolated double for spawned selection CLI tests. These doubles are **not in
the patch, wheel or sdist**, and production code has no fake-word fallback.
Actual UUIDv4 generation, collision retries, name validation, renaming, identity
stability and metadata privacy were exercised. The 12 non-selection PTY tests did
not require a naming double. A complete checkout validation with real coolname is:

```bash
python -m pip install -e '.[dev,pdf]'
python -m pytest --cov=twhy --cov-report=term-missing
```

Do not interpret these checks as an installed-coolname integration test or a test
of its full vocabulary. The shipped smoke test runs when the dependency is
installed normally.

The generated git patch passed `git apply --check`, then `git apply`, against
a second exact reconstruction of the supplied snapshot. All changed/added files
matched the working tree byte-for-byte. The applied tree was retested with the
same external naming fixture: **427 passed, one skipped**.

### New behavior covered

Checks include independent rectangle/polygon names and UUIDv4 IDs, stable IDs
across repeated exports and renames, generated-name collision retries, empty
name/control-character rejection, exact minimal exported properties, anonymous
suggested filenames, and no automatically inherited path, filename, page, series,
channel label or image dimensions. Renaming during an asynchronous save cannot
change that save's already-captured identity or content.

Union tests check concave shapes, overlaps, disjoint gaps, reverse winding,
cell-center inclusion, immutable text masks, original foreground/background
colors inside selected cells, reset-style spaces outside, and absent hidden RGB
values. Polygon PNG alpha follows pixel centers, not entire terminal cells;
fully excluded pixels have **all four RGBA bytes zero**. Valid dark pixels inside
selected regions remain opaque. Exported PNGs do not contain inherited metadata.
The image-intersection tests check actual polygon clipping rather than moving
individual out-of-bounds vertices, and reject empty/degenerate results.

The actual terminal application exercises all eight copy/save shortcuts for a
polygon, first-point/Enter closure, reopening, adding mixed shapes, choosing and
renaming an earlier area, removal, untouched empty drafts, explicit errors for
unfinished shapes, and space/alpha padding in combined exports. A real CLI PTY
workflow creates a rectangle and polygon, writes a two-feature anonymous
GeoJSON, saves RGBA PNG, toggles ASCII, and verifies identical escape-free ASCII
text and ANSI-destination bytes. Exit restores alternate screen, mouse and cursor.

The channel fixture has **128 real synthetic OME-TIFF channels**. Tests reach
both ends with PageUp/PageDown/Home/End, solo channel 127, scroll with the mouse,
check hit-testing after scrolling, and shrink the terminal while retaining the
focused channel. Focusing/paging alone does not request image samples. Compact
selection toolbars retain all format pairs at 45, 60 and 80 columns.

ASCII selection preview reuses retained ViewSamples and leaves coordinates and
IDs untouched; a test forbids any new sample read. Full-terminal rename/save
prompts overlay the last row without shrinking the canvas or clearing multiple
areas. Single-rectangle native PDF text copying remains covered by the previous
real PDF rotation/CropBox tests. Polygon and multi-area PDF text uses the explicit
masked-screen contract; a test forbids a larger native-text bounding-box query.

The baseline's fullscreen Escape test failed because it asserted before the
terminal Escape-sequence timeout elapsed. Its wait now observes actual state;
the runtime Escape parser and timeout are unchanged.

### Visual inspection and environment

A real prompt_toolkit character/style screen was reconstructed as an inspection
PNG, and a real union PNG was inspected against a checkerboard. Both region
outlines, active-area status/name, compact toolbar, and the transparent gap and
subcell polygon edges were checked. These are reconstructions of actual output,
not native desktop screenshots. Synthetic fixtures, local inspection fonts,
inspection images, and external naming doubles are not shipped.

Linux/Python 3.13.5; NumPy 2.3.5, SciPy 1.17.0, Pillow 12.3.0, pypdfium2 5.8.0,
tifffile 2026.5.15, prompt_toolkit 3.0.52, pytest 9.0.2, setuptools 82.0.1.
Integration used the actual Omeify 0.21.0 source recovered from the available
`6d9f5ff` snapshot, with runtime Python source byte sizes verified. It was not an
imitation of the Image API or a test of a separately installed Omeify PyPI wheel.
POSIX PTY runs reported the test harness's Python 3.13 forkpty deprecation warning.

All 52 source/test/example Python files parse with Python 3.11 grammar. Wheel
and source-distribution builds succeeded via the installed setuptools backend.
Wheel contents include the three new modules and the coolname dependency, but
no vendored reader/naming package or font files. The build frontend and Ruff
executable were unavailable.

### Limits

Selections are limited to one frozen view, at most 256 areas. There is no
cross-page/series/camera selection persistence, hole/subtraction tool, OCR, or
polygon-filtered native PDF text. Clipping that would split one concave polygon
into disconnected components is rejected rather than given invented connecting
edges. PDF GeoJSON is on the frozen raster pixel grid, not a cross-DPI reference.
Native QuPath import was not exercised.

An actual Python 3.11 runtime, native desktop clipboards/alpha-paste acceptance,
live SSH/tmux/Screen transports, macOS/Windows terminals and production mIF slides
were not tested. PNG files are the portable alpha-preserving output; a receiving
clipboard application may flatten them. Export metadata minimization does not
remove identifying content in selected pixels, selected text, or user labels.
Previously exported files are not automatically rewritten.

## Symmetric selection shortcuts and two rendering families (October 2026)

This incremental change targets the attached `244deaf18b87934cf7e7ff8e562a7ea686eca77d`
snapshot. Selection copy/save bindings are now lowercase/uppercase pairs:
`y/Y` text, `i/I` PNG, `t/T` ANSI text art, and `j/J` GeoJSON.
The retired `w/W/P` selection bindings are not kept as aliases.
Normal browsing `t` still toggles color; the selection context uses `t` to copy ANSI.
No export encoding, GeoJSON metadata, UUID lifecycle, image sampling algorithm,
source-read budget, Python minimum or dependency changes are introduced.

Rendering navigation now has independent state for colored `m` styles
(detail/shape/simple/blocks) and strict ASCII `M` styles
(classic/fine/bold ramps of the existing simple renderer). The first keypress
when crossing families restores that family's remembered style; subsequent
keypresses advance its cycle. No one-shot restore flag is used. The current
style and both keys remain visible in the existing compact status/footer.
During selections, both families render from cached display samples. The
unmodified, frozen source frame remains available; style previews cannot
move areas or change their names, IDs or masks. The browsing renderer is
not changed by selection-only mode navigation.

**Executed here:** 99 focused and renderer-regression tests passed, including
7 new tests for mode sequences, custom ramps, independent color/ASCII state,
symmetric key dispatch in both selection tools, a frozen multi-selection
without new source reads, and actual prompt_toolkit input handling and file
exports using a file-free synthetic session. The renderer's legacy byte-level
goldens passed. All source, test and example Python modules parse under the
Python 3.11 grammar. The final patch was verified against a separate clean
reconstruction of all 61 files with matching byte lengths and final-newline
flags.

**Limitations:** The environment lacks the installed Omeify and coolname
packages. The focused 99-test run includes the existing GeoJSON tests with a
temporary, out-of-tree naming double, not the published coolname distribution.
The full Omeify-backed tests, native desktop clipboard acceptance, and live
macOS/Windows terminal input were not run here. The out-of-tree naming double
is not packaged in twhy or included in this patch.

## Aperio SVS file ingress (October 2026)

This patch targets the attached twhy `d3514ef7ad58e59eec3b1fc821d7516398aa8010`
snapshot. It selects Omeify's public `AperioSVSReader` for TIFF-signature files
with a case-insensitive `.svs` suffix and retains `OMETiffReader` for other TIFF
paths. Existing TIFF document-series navigation, RGB presentation, regional
sampling, read budgets and snapshot handling are shared. No new dependency,
Python minimum or package-version change is needed; Omeify >=0.21.0 already
exports this reader.

The TIFF signature check precedes suffix dispatch. `AperioSVSReader` validates
the actual vendor container and fails on a renamed non-Aperio TIFF. SVS files
with a different extension are not automatically recognized. No TIFF source
pixels are decoded using Pillow, materialized as a whole slide by twhy, or
converted into an in-memory dyadic pyramid. Omeify's native levels are used
when present; unavailable/unknown pyramid scales remain subject to the same
labelled approximate mapping and read-budget limits as other TIFFs.

**Executed in this environment:** routing tests for lower/uppercase `.svs`,
non-TIFF signatures, and wrong-kind arguments, plus a tifffile-produced Aperio
synthetic fixture with a base image, an associated thumbnail and two stored
reduced levels. The fixture uses lossless Deflate rather than vendor JPEG to
avoid imposing a codec-dependent baseline. The real Omeify integration tests
check the vendor reader, exact regional pixels at every level, MPP-derived
calibration, RGB channels, bounded `ViewSession` sampling, document selection,
snapshot ANSI output, and non-Aperio rejection when Omeify is installed.

**Outstanding:** this environment does not contain the actual Omeify package,
and it could not be installed via the unavailable package network. Integration
tests requiring it are skipped here, not counted as executed. A real production
Aperio JPEG/JPEG 2000-compressed SVS (and macOS/remote terminal behavior) still
needs an end-to-end smoke test. Do not infer diagnostic color correctness or a
process-memory upper bound from the synthetic fixture. Run the suite in the
normal twhy environment and inspect a real scanner file before relying on this
format in production.

## Interactive whole-image zoom-out through bounded sampled overviews (October 2026)

This update applies to the supplied twhy `34444adc163b3dd51d53e83beefeacd423057556`
snapshot. The original `Viewport` already allowed letterboxed negative origins;
the issue was the source-read budget. When an SVS/OME-TIFF coarsest level was
still too large, initial `fit()` zoomed to a center crop and the viewer rejected
further zoom-out. The new *interactive-only* sampled-overview path permits a
full-frame display with no more source pixels requested than the existing budget,
while labelling the interpolated patch overview as approximate. The `r`/Home
shortcut now explicitly requests the full image. Initial opening, strict library
planning, noninteractive snapshots, PDF upgrade fidelity checks, source ownership,
and precise within-budget regional sampling retain their prior behavior.

**Executed checks:** 72 tests passed covering the new portrait/landscape/no-pyramid
and tiny-budget tests, actual synthetic Aperio SVS and OME-TIFF decoding, source
sampling, and PDF document navigation. A separate 197-test run passed the
renderer, viewer, interactive mode/navigation, image-ingress, and CLI groups.
The 9 new tests appear in both groups, so the totals should not be added without
deduplication. The tests include a real prompt_toolkit keyboard session where
`-` reveals a complete portrait slide with black side margins, `r` requests
whole-slide fit, and returning to zoom-in removes the sampled-overview marker.
Regional read calls and their aggregate RGB/sample counts are asserted to remain
within `max_read_pixels`. No full-slide synthetic image was allocated.

Testing used Python 3.13, the reconstructed Omeify 0.22.0 source from the
provided `97c97ef` snapshot, tifffile, NumPy, SciPy and prompt_toolkit.
Synthetic SVS uses lossless Deflate to keep the test independent of scanner JPEG
codecs. No real vendor JPEG SVS, macOS native terminal, or high-latency storage
source was exercised. The source-proportional sampled overview is not guaranteed
to retain tiny tissue structures between its sampled patches and is not suitable
for morphometric analysis.

Broader selection test runs exposed outdated baseline expectations for retired
`w` and historical `m` shortcuts; these unrelated behaviors were not changed.
The real `coolname` distribution and TIFF JPEG codecs were unavailable in this
environment; an explicitly out-of-tree test double was used for non-vocabulary
selection tests only, not bundled with the patch.

## Incremental full-coverage runtime overview cache (October 2026)

This candidate targets the supplied `b37dcef043b45889d907972c1c28c4d764bf5060`
snapshot. All 66 baseline files were reconstructed with byte sizes and final
newline flags verified. No dependency, Python minimum, package-version, source
calibration, GeoJSON geometry, or image-reader change is introduced.

**Executed:** 374 tests passed in one final selected regression run, including
44 new runtime-overview cases and a real POSIX pseudo-terminal SVS workflow.
The new PTY test opens an independently generated Deflate Aperio fixture, fits
the whole slide, observes `cached overview`, and verifies clean exit and restored
alternate-screen, mouse and cursor state. Python 3.13 emits one forkpty
DeprecationWarning from that test harness; it is not a viewer failure.

Numerical cases compare all native pixels against an independent per-pixel
weighted oracle, including RGB/scalar, odd and one-pixel-wide shapes, nonfinite
samples, fractional edge support, and reduction blocks larger than a read chunk.
They assert exactly one visit per native pixel and per-chunk sample limits.
Additional cases cover uint32 precision, a corner feature missed by sparse
sampling but included in the integrated cache, native-detail preference,
multichannel LRU retention/eviction, combined finished/unfinished byte limits,
scan limits and disabled preparation, incomplete-build cancellation, source
close/reopen invalidation, and no automatic retry after a deliberate read error.

Actual Omeify SVS and OME-TIFF integrations prohibit whole-page/whole-series
materialization while preparing a cache. Unknown-scale geometry keeps the
extent-fit marker; declared anisotropic/odd-size geometry stays unchanged.
Interactive tests exercise same-camera/same-contrast refinement, frozen-frame
selection, foreground preemption, source changes while a chunk is in flight,
shutdown with an in-flight chunk, budget propagation through CLI/navigation, and
unchanged noninteractive snapshot policy. The previous sampled-overview viewer
tests now explicitly disable preparation to test that fallback deterministically.

Final regression command:

```bash
python -m pytest -q --ignore=tests/test_pty.py --ignore=tests/test_clipping.py \
  --ignore=tests/test_multiselection.py --ignore=tests/test_geojson_clip.py
```

This includes the new PTY test in `test_runtime_overview.py`, but not the separate
historical PTY module. An attempted combined historical PTY run reached the
execution time limit after nine completed cases, without a completed summary;
it is not counted as a passing full run. The three omitted selection/export
groups require the unavailable real coolname dependency and/or contain known
historical shortcut expectations. No replacement naming package was used for
this candidate's tests. The full repository suite is not claimed to pass.

Environment: Linux, Python 3.13.5, actual Omeify 0.22.0 source reconstructed from
the supplied `97c97ef` snapshot, NumPy, SciPy, tifffile, Pillow, PDFium and
prompt_toolkit. This tests the real source dependency, not its separately
published wheel. Ruff could not be installed in this environment. Python 3.11
syntax parsing, whitespace checks, and application of the patch to a separate
clean baseline reconstruction are checked separately.

No production scanner JPEG/JPEG 2000 SVS, high-latency filesystem, macOS/Windows
terminal, live SSH/tmux transport, or process-RSS benchmark was exercised. Native
decoder tiles/strips and temporary reduction/resampling buffers are outside the
array-cache cap. Cancellation occurs between regional chunks; the current native
read is joined, not forcibly killed. A completed cache is full-coverage relative
to its chosen native level, not a guarantee of exact full-resolution statistics
or recovery of features already lost by the scanner's coarse level.


## Quick whole-slide startup and snapshots (October 2026)

This incremental patch targets the supplied `65955f525e793b0bffe34587692961f723488789`
snapshot. A metadata-only check immediately fits the full image if a suitable
native pyramid rectangle is within the per-request budget. Otherwise a cached
full-coverage overview may be prepared for up to two seconds before the first
interactive frame, only when the coarsest native level contains no more than
8,388,608 selected source samples (including RGB components). The existing cache
memory, total-scan and per-chunk work caps still apply. Native reads are
cooperatively cancellable between chunks, never forcibly interrupted. Slow or
ineligible scans preserve the responsive original bounded-crop opening.

Snapshots now use the same quick preparation and **always fit the whole image**
when no explicit region is supplied: native region when affordable, completed
cached reduction if quick, and labelled sampled fallback otherwise. The existing
`--region` geometry/strict budget, snapshot atomic writes and output modes remain
unchanged. `--startup-overview-seconds 0` skips pre-first-frame scanning but does
not prevent normal interactive idle preparation. Output may vary by I/O timing
between cached and sparse reductions. The startup time limit does not impose a
hard timeout on an already-running native TIFF codec call.

Executed regression run: **386 passed, one warning**, with the existing PTY,
clipping, multiselection and GeoJSON historical test modules excluded. The suite
used actual Omeify 0.22.0 source from the available `97c97ef` snapshot, not a
mocked TIFF reader. New cases include immediate native letterbox, full-coverage
cache before the first frame, time-limit fallback, user-zoom preemption, metadata
work-cap rejection, actual synthetic Aperio SVS and OME-TIFF decoding, full-slide
snapshot under tiny budgets, explicit region and a snapshot from a real SVS
fixture. Python 3.11 grammar parsing passes; this was executed under Python 3.13.

The entire historical suite, production JPEG SVS, remote/slow network
filesystems and native macOS terminal behavior remain separate validation
requirements. Native codec calls cannot be forcibly timed out and RAM budgets
do not include third-party decoder caches or temporary codec scratch.

## Whole-slide initial camera in the interactive viewer (October 21, 2026)

This patch targets the supplied `37c5c1a31c91cf99b2c734a0cf93f679f83d419d`
snapshot. The previous quick-startup change made **snapshots** cover the whole
image, but the interactive `Viewer.fit()` still called strict `ViewSession.fit()`
when a native overview was over budget and a complete runtime reduction was not
ready. That helper intentionally zooms into a bounded center crop. A tall SVS
can therefore open severely zoomed in even with the normal 4,194,304-sample
foreground budget when its coarsest stored level contains more samples.

The interactive **initial camera now always uses `Viewport.fit()`**. If native
regional sampling is inexpensive it is used unchanged. If a quick full-coverage
runtime reduction finishes it is reused. Otherwise the first frame displays
the same visibly labelled, read-budgeted *sampled overview* used by snapshots.
Idle caching may refine the samples without changing the camera. No entire
native level is materialized. `--region` still selects its exact requested
viewport. The public library `ViewSession.fit()` remains a deliberately strict
bounded-crop operation; the viewer no longer uses it for automatic opening.

**Executed tests:** 388 selected regression cases passed with one warning; one
additional actual POSIX pseudo-terminal case passed independently with one
Python 3.13 `forkpty` deprecation warning. The terminal test opens a real
synthetic Aperio SVS via the default CLI without pressing `r` and observes a
sampled full-image first frame. Other regression tests check native affordable
fits, fast cached starts, a tiny startup deadline, startup work caps, the normal
4-million-sample budget on a large procedural portrait slide, an explicit
initial region, zoom and Home/r restoration, and cache/foreground preemption.
The combined run reached its execution time limit after nearly all cases and
is **not** reported as a separate passing run. Actual native macOS terminal,
scanner JPEG/JPEG 2000 SVS, and high-latency storage still require field tests.

## No-flash full-coverage startup (October 21, 2026)

This patch targets the supplied `bbdf20cf20fc83fd80aaa558c4200f0d9b1730ad`
snapshot. The previous whole-image opening policy still had an independent,
hard-coded 8,388,608-source-sample eligibility gate. For larger but quickly
readable coarsest levels, the interactive viewer skipped its configured
`--startup-overview-seconds` attempt, displayed a sparse overview immediately,
and only then published an idle-time full-coverage reduction. Raising the
startup time limit could not change that behavior.

The quick-start eligibility decision now uses the **same configurable total
source-scan and RAM caps** as the idle overview cache, without a second fixed
sample-count cutoff. The existing single render worker spends at most the
requested startup interval attempting the complete reduction before submitting
the first image frame. A completed cache is used for that first image, without
painting a sparse image beforehand. A scan exceeding its time budget, disabled
cache, or ineligible scan falls back to the existing sparse first frame; idle
preparation remains available. Navigation still preempts future chunks, and
native codec calls cannot be interrupted or strictly time-bounded mid-read.
`--region`, PDF refinement, viewer camera geometry, and Omeify are unchanged.

**Executed validation:** 391 selected tests passed, with two Python 3.13
`forkpty` deprecation warnings from actual POSIX terminal cases. The selected
suite excluded the historical `test_pty.py`, `test_clipping.py`,
`test_multiselection.py`, and `test_geojson_clip.py` modules. Included were
startup and runtime cache tests, actual synthetic Aperio SVS/OME-TIFF readers,
CLI snapshots, document navigation, and other non-PTY regressions. A new
procedural 64,000-by-14,000 RGB slide has 10,500,000 coarse-level samples and
can complete its cached reduction quickly. The test records every produced
image frame and asserts the **first** one is cached, rather than checking only
a later improved frame. The same larger slide exercises synchronous snapshot
preparation. Work-cap rejection, a short deadline, and user-command preemption
are also tested. All Python modules parse under Python 3.11 grammar. This is
not production JPEG-SVS, high-latency storage, or native macOS terminal testing.


## Remote/Zarr ingestion and package identity (October 24, 2026)

Against snapshot `3946c7a`, distribution metadata becomes `twhy`;
CLI and import retain `twhy`. Omeify minimum is 0.22.1, including Zarr reader,
and optional `[s3]` supplies s3fs through Omeify. The remote resource boundary
stages only bounded single-file objects, not Zarr stores. PDF staging persists
through document navigation, worker refinement, and clipping. Shifted pyramid
levels are excluded from render planning to prevent offset misregistration.

Test commands: `python -m pytest -q tests/test_remote_input.py`, the full
regression suite with installed Omeify 0.22.1, Zarr, imagecodecs and coolname,
then the actual installed-wheel smoke lane. Test remote-S3 behavior against an
authorized endpoint separately; out-of-tree S3 transport spies are routing
checks, not a real S3 integration test. Do not confuse an available local
HTTP server with production object-store validation.

## Per-channel color controls (October 24, 2026)

This patch targets `ef5f9f4caa6f2fffc8e0bfd9523b34bd4c505f1b`. All 72 source
snapshot files were reconstructed with their byte sizes and final-newline flags
checked. It adds `h` color entry, clickable channel swatches and the focused color
row, and repeatable `--channel-color INDEX COLOR` overrides. Existing `l/u/g`
shortcuts, exact default palette values, numerical windows, source pixels,
version 0.2.0, and dependency requirements are unchanged.

### Executed checks

**567 tests passed and one skipped across two disjoint regression runs:**
466 passed in the main lane and 101 passed/one skipped in the additional
clipboard, geometry, PDF-text, channel-paging and terminal lane. The main lane
includes **all 67 new color tests**. The additional lane's skip is the existing
real-coolname vocabulary test: that distribution is unavailable in this execution
environment and package-download access failed. The final runs exclude 38 other
existing selection/naming-dependent cases, not the new color tests. An attempted
full run encountered missing-coolname selection failures and was stopped; this
is **not a claim that the complete repository suite passed**. No global naming
substitute was installed. Individual tests that intentionally isolate naming
use their own deterministic fixtures, as the existing unit tests do.

The main regression command was:

```bash
python -m pytest -q --ignore=tests/test_clipping.py \
  --ignore=tests/test_multiselection.py --ignore=tests/test_geojson_clip.py \
  --ignore=tests/test_pty.py
```

The additional disjoint run exercised the synchronous clipping/geometry/PNG
checks, native PDF rectangle extraction, selected identity/mask unit tests,
128-channel paging, the PDF-worker cancellation regression, and all twelve
non-selection cases in `test_pty.py`. The new color module itself includes another
real PTY test; two existing overview PTY cases are in the main lane. The fifteen
warnings across these lanes were Python 3.13 forkpty deprecation warnings from
the terminal harness, not failed assertions.

New tests cover strict hex/name/default parsing, invalid/duplicate/out-of-range
CLI options, default-rendering equivalence in all four modes, independent
channel ordering, hidden/unread channels, unchanged numeric windows, no-op Enter
without color quantization, invalid entry and cancellation, monochrome behavior,
full-terminal entry, swatch hit testing, wide Unicode labels, and source/series
changes while entry is pending. Native RGB rejects pseudocoloring. Startup colors
are propagated through both file-viewer paths and snapshots.

A real Omeify-backed session with its preview LRU disabled forbids further
`sample()` calls while testing repeated color edits: the displayed samples are
reused. Separate tests require normal reads when the camera changed, and require
a newly completed runtime overview to replace an old sparse preview rather than
getting stuck behind a queued color request. Frozen selection mode changes keep
the chosen palette. Actual saved PNG and ANSI clips are checked for the expected
RGB bytes/codes. The terminal test enters `h`, types `#3366ff`, observes its color
escape codes, and checks restored terminal screen/mouse/cursor state on exit.

### Visual, build, and environment checks

The actual prompt_toolkit screen was captured and reconstructed for inspection
with a local font. The focused-channel color row, right-aligned swatches, limits,
gamma, footer, and unchanged image area were inspected. A real SGR mouse click
on channel 1's swatch opened that editor without changing selected channels.
The inspection image and font are not part of the patch or package.

Linux, Python 3.13.5, NumPy 2.3.5, SciPy 1.17.0, Pillow 12.3.0,
prompt_toolkit 3.0.52, pypdfium2 5.8.0, tifffile 2026.5.15, and pytest 9.0.2.
TIFF and Image integration uses the actual Omeify 0.22.1 source reconstructed
from the previously supplied `077d285` snapshot, not a mocked reader. All 65
source/test/example Python modules parse with Python 3.11 grammar. This is not
an executed Python 3.11 runtime or minimum-dependency test.

Wheel and sdist construction passed through the installed setuptools backend.
The wheel was installed outside the checkout and rendered a real OME-TIFF
snapshot with the requested `#3366FF` foreground/background codes. That smoke
check reused this environment's numerical dependencies and the real Omeify
source; it does not certify a fresh PyPI dependency resolution. The generated
patch was checked/applied to a fresh exact reconstruction and its resulting
files compared byte-for-byte with the tested working tree.

Native macOS/Windows terminal behavior, actual desktop clipboards, SSH/tmux,
production slides and real remote Zarr/S3 stores were not exercised by this
color-control pass. The existing source/transport behavior is unchanged. Colors
remain display-only and session-local, with series changes resetting the palette.


## Monochrome artwork and independent m/M navigation (October 24, 2026)

This patch targets `46cf6f3f6cc57f6b27c64a8e5bfe2cf5f1fbc7f0`. The prior
`ModeNavigation` inferred a rendering family from `TextRenderer.color`, so the
`m` key forced colored output and monochrome Braille/shape were unreachable
through its cycle. The two concepts are now independent: `m` is the remembered
artwork family, `M` is a separate always-monochrome strict-ASCII ramp family,
and `t` toggles the artwork family's color preference. Monochrome `m` cycles
only detail/shape/simple; color enables half-blocks as a fourth style. Switching
families first restores the saved style. `b` retains temporary half-block preview
with an exact restoration path for monochrome art *and* strict ASCII. Inversion
while in an ASCII ramp preserves that ramp. A reported 1-bit/`NO_COLOR=1`
interactive terminal initializes the renderer in monochrome unless the caller
explicitly requests `--color`.

**Executed regression checks (overlapping lanes, not additive):** 81 passed for
viewer/mode navigation/terminal/CLI/legacy; 108 passed for color controls,
terminal capabilities and CLI; 145 passed for numerical renderers, terminal
capabilities, and source sessions; 70 passed for sampled/startup/runtime
whole-slide overview cases (including two real PTY runs); 108 passed for image,
SVS and remote-input cases; and 31 passed for document navigation. Twenty
selected multiselection/clip tests also passed with a temporary, out-of-tree
`coolname` name-generator substitute, including frozen selection `m/M` previews
without new image reads. The substitute is not in the patch or wheel. The real
`coolname` package was unavailable here, so the full naming-dependent suite
was not verified; a broader invocation produced missing-package failures and
a combined slow suite exceeded the runner's deadline. These are not presented
as a complete green suite. One Python 3.13 `forkpty` deprecation warning was
observed in the color-control lane and two in the overview lane.

No reader, sampling algorithm, pixel/ROI geometry, package/dependency minimum,
or snapshot rendering default was deliberately changed. New tests include
monochrome m cycles and skip-block invariants, `t` inside M, temporary b
round-trips, custom ramps, startup `NO_COLOR`, and actual prompt_toolkit key
input. Native macOS/Windows terminals and live SSH/tmux transports were not
exercised in this pass.


## PDF available in the standard install (October 25, 2026)

This packaging-only update targets the supplied `08f65f2` repository snapshot.
`pypdfium2>=4.30,<6` moves from the opt-in `[pdf]` extra into core dependencies,
and `[pdf]` is removed. S3 remains opt-in under `[s3]`. The standard install
`python -m pip install twhy` now includes PDF support. CLI-only users
can install with `pipx install twhy` or `uv tool install twhy`.

PDFium remains lazy-imported when PDF content is opened. Image rendering, page
navigation, memory limits, PDF worker management, source decoding, Python minimum
and NumPy compatibility requirements are unchanged. A damaged or `--no-deps`
installation without PDFium now reports that a required dependency is missing,
rather than incorrectly directing users to install an optional extra.

The earlier validation sections record historical package configurations and
commands from when PDF was optional; current installation guidance is in the
README and `pyproject.toml`.

## Z/T navigation over persistent Omeify datasets (October 31, 2026)

Targets the exact supplied twhy `35a38c81d193c5b26fd2e3beeac835ba488d2704`
(`t_z_support`) and Omeify `74bf991b4f2bc71ab629b449fe8c143057bb97f8`
(`z_t_support`). The 76 included twhy text files and all 188 Omeify files were
reconstructed with exact byte counts and final-newline checks. Ten binary demo
media files omitted by the twhy snapshot were not recreated or modified.

### Implementation

Z/T/Series selection extends the existing document navigator, single source-loader
thread and single display worker. Omeify remains the only OME decoder. A retained
public ImageDataset yields immutable plane Images, each with a fresh ViewSession.
Z/T changes preserve camera, channel selection/focus, colors and contrast; series
changes initialize their own state. `d`, clickable dimension chips, brackets,
PageUp/PageDown and `p` use the same frontend in TIFF and Zarr. Omitted startup
indices default to zero only in twhy's explicit frontend policy. Stable-image
Python calls remain strict unless `first_plane=True` is supplied.

Ordinary channel/level switches no longer flush the provider cache. Automatic
zoom consumes only each selected Image's exact-section-compatible levels.
No XYZ coarse-volume substitution, Z projection, time playback, speculative
Omeify prefetch, new runtime dependency or change to anonymous GeoJSON is added.
Omeify's source tree is unchanged. The dependency floor becomes 0.22.2, but use
the specified Omeify branch revision until an actual release contains this API.

### Executed checks and explicit gaps

**This environment did not produce an all-green full suite.** It lacks the real
`zarr`, `ome-schema`, `imagecodecs` and `coolname` distributions. Package install
and download attempts failed. No substitute reader, codec or globally injected
naming package was installed to disguise those missing dependencies.

* Complete suite attempt: **630 passed, 59 failed, one skipped**, 19 warnings.
  Twenty newly added Zarr cases stopped at the missing `zarr` import; the new
  public-writer demo test stopped at missing `ome-schema`. The other 38 failures
  are existing naming-dependent selection/terminal cases. All 38 were rerun on
  the untouched twhy snapshot and failed there too. The skip is the existing
  real-coolname vocabulary test.
* With those 59 specifically identified cases deselected: **630 passed, one
  skipped, 59 deselected**, 16 Python 3.13 `forkpty` warnings. This is a selected
  regression result, not a claim that all dependencies or formats were tested.
* The new Z/T modules contain **61 cases**: **40 executable TIFF/UI/pyramid cases
  passed**; the 21 real-Zarr/public-writer cases above remain unverified. A separate
  new dependency-floor packaging assertion also passed. Real Zarr tests are not
  converted to skips and must run with the actual declared dependencies.
* Seven independent pre/post CLI comparisons matched stdout and stderr
  byte-for-byte: scalar TIFF, multichannel TIFF, RGB ANSI TIFF, PNG, PDF, sparse
  overview and explicit-region snapshots. Both trees used the same real Omeify
  source. This is not a claim of equivalence for every file or terminal.

Tests use actual TIFF files written independently with tifffile, including all six
T/C/Z orders, RGB, Z-only, T-only, combined Z/T and multiple series. They assert
exact requested pixels, shared cache reuse, invalid-index rejection, source-handle
ownership, stale-load/frame rejection, failed-load recovery, loader/display
shutdown ordering, camera/window/color preservation, sidebar focus, fullscreen,
clickable dimensions, frozen selections, snapshots and real POSIX PTY restoration.
One new selection-freeze test supplies a fixed per-test annotation identity to
isolate unrelated naming; it does not validate coolname. File-free mixed-XYZ
providers exercise the real Omeify plane adapter and twhy renderer without
pretending to be Zarr codec tests.

The existing remote-collection routing unit test now spies on the public dataset
entry point and public inspector instead of the fixed-plane reader. It uses an
array-backed real Omeify dataset and explicitly does not establish Zarr I/O.
Two existing snapshot tests previously counted diagnostics as image rows under
Click 8.1's CliRunner stderr mixing. Both failures reproduced unchanged on the
baseline; they now check actual snapshot files separately from diagnostic text.
No application output behavior was changed for that test correction.

### Visual, packaging and environment checks

The actual prompt_toolkit character/style screen was captured at 100 and 60
columns after navigating a synthetic Z/T TIFF. Reconstructions of those screens
were visually inspected: Z/T chips, active-axis marker, current indices and the
unchanged image/sidebar geometry were legible. These are actual UI-cell captures,
not generated mockups or screenshots of a native macOS terminal. A local font used
only to inspect the captures is not included in the patch, package or bundle.

All **72 Python source/test/example modules** parse under Python 3.11 grammar.
Execution used Linux/Python 3.13.5, NumPy 2.3.5, SciPy 1.17.0, tifffile 2026.5.15,
prompt_toolkit 3.0.52, pypdfium2 5.8.0, pytest 9.0.2 and Click 8.1.8. Wheel and
source-distribution builds succeeded through setuptools 82.0.1's real build
backend, including the new module, demo and declared Omeify minimum. A separately
resolved fresh dependency installation and a Python 3.11 runtime were not tested.
The Ruff executable and `build` command frontend were unavailable.

Public IDR catalog references were rechecked, but actual public-store chunk I/O,
S3 service access, production-slide latency, live SSH/tmux, native macOS/Windows
terminals and large-volume memory behavior were not tested. The included demo
uses real public writers and remains behind the missing-dependency verification
gap. Run `python -m pytest -q tests/test_zt*.py` and the complete suite in the
fully installed development environment before calling this integration green.


## Pyramid-guided contrast and histogram refinement (October 31, 2026)

This refinement targets `f8f0ece` with Omeify `6e926f2` (0.23.0).
The [complete validation record](contrast-validation.md) distinguishes executed
statistics/UI/TIFF tests from dependency-blocked real Zarr integration.
The full attempted suite yielded 688 passes, 65 dependency-blocked failures and
one skip; the available-dependency lane yielded 688 passes, one skip and
65 explicit deselections. These are not two independent passing full suites.
See [methods and statistical scope](contrast-estimation.md) for the population,
weights, separate display policy, bootstrap qualifications, and evaluation plan.
