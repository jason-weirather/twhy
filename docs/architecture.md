# Rendering boundary and extension notes

## Public workflow

```
Omeify Image + Viewport
    -> ViewSession.plan()
    -> ViewSession.sample()
    -> ViewSession.prepare_styles() or explicit ChannelStyle values
    -> ViewSession.render()
    -> TextImage
```

The file-free operations `IntensityWindow.apply`, `resample_image`,
`compose_channels`, and `TextRenderer.render` are separate public stages, not
private functionality only reachable through the viewer. `TextImage.iter_runs`
provides structured presentation for integrations without depending on ANSI or
prompt_toolkit.

## Modules

Snapshots call `image_input.open_image()` and pass its open Omeify Image to
`ViewSession`. The interactive file entry point is `viewer.view_file()`. It uses
`ImageDocument` for PDF/OME selection and `DocumentNavigation` for controls,
source ownership, progressive PDF work and the page cache. Both paths still use
the same `ViewSession` and renderer. OME-TIFF and OME-Zarr browsing use
Omeify's persistent `open_dataset()` sessions and borrowed immutable plane Images;
Aperio `.svs` TIFFs retain `AperioSVSReader`. All expose the public Omeify Image,
regional reads and supplied levels. Ordinary files and completed PDF
rasters are wrapped through Omeify's public array API.

`view_info.py` derives display geometry from the public image descriptor.
`ViewSession` borrows a stable, open Omeify image. Its Image/ImageSource contract,
read budget, raw-preview cache and rendering stages are unchanged. File, array
and externally implemented procedural sources share this path. There is no
second TIFF decoder and no dependency on Tilework or Mocktome.

`viewport.py` owns camera geometry. `view_session.py` owns planning, read budgeting,
preview sampling, preview cache, and orchestration of normalization/rendering.
`resampling.py` performs separable area integration with sparse overlap matrices.
Partial edge cells average covered finite pixels only; uncovered cells are NaN.
Known pyramid scale factors come from Omeify ImageLevel.downsample_yx. An
odd-sized base can truncate the final coarse pixel's support; the resampler clips
that support at the true image edge. Unknown scale uses explicitly approximate
extent-fit display mapping. This fallback neither changes image calibration nor
claims knowledge of a vendor resize kernel.

The viewport permits negative origins (letterboxing). Initial `fit()` preserves
its native-read/bounded-center-crop contract. Interactive plans may fall back to
a coarser complete native rectangle, then to the labelled sparse grid in
`sampled_overview.py` when no native region fits the foreground budget.

`runtime_overview.py` adds an optional session-local display cache, not a new
Omeify ImageSource, source pyramid level, reader or calibration. `step_overview()`
performs one bounded native regional read on the existing display executor.
Every source pixel of the coarsest level is visited once per completed channel
build. Integer power-of-two blocks accumulate float64 weighted values and finite
support, including partial native edge footprints. The arrays are normalized by
actual output-cell support in place and published read-only only on completion.
Two-stage area sampling is a display approximation within each reduced pixel;
full coverage does not mean exact arbitrary-footprint full-resolution statistics.

The LRU byte cap includes one unfinished build plus completed channel entries.
Resolution is chosen so the complete selected channel set fits, avoiding mutual
eviction/thrashing. Other channel entries are evictable. A separate selected-set
source-sample cap declines costly automatic scans; it is not the per-chunk limit.
Native decoder caches, scratch and retained ViewSamples are separate allocations.

Planning stays metadata-only and deterministic, independent of cache readiness.
For an explicitly allowed sparse ReadPlan, `sample()` first looks for a complete
cached channel set and sets `ViewSamples.cached_overview` on cache use. This keeps
outstanding plans valid while preparation progresses. Plan source_samples is the
planned sparse budget, not a claim of source I/O on a cache hit. Publication
invalidates old sparse camera-preview cache entries, not already-issued immutable
ViewSamples. Strict library plans and PDF source-upgrade fidelity checks do not
silently opt into these display reductions. Source geometry is never rewritten.

The render pump services foreground requests before another overview chunk. A
shared, metadata-only startup policy always selects the whole-image camera.
Native levels are used when affordable; otherwise, for sources within the
configured overview scan and cache limits, the render pump may attempt up to
two seconds of chunked work before the first image frame. There is no separate
fixed sample-count gate at startup. No sparse image is drawn during the timed
attempt: a completed cache becomes the first image, otherwise the camera
displays the labelled sampled overview, not a center crop. User interaction and navigation invalidate the
startup generation, preventing late preparation from moving the camera. After
the first frame, ordinary idle preparation
resumes, yielding between chunks, with no second source-reader thread. Selection pauses further
steps and guards against frame replacement after an in-flight step. Navigation
installs sources only after the current worker operation finishes, then releases
the old overview cache. Shutdown joins one current read, not a whole-level scan.
Channel changes discard obsolete partial work on the next step. Completed results
remain useful across camera, contrast and renderer changes. Errors abandon the
partial arrays and suppress automatic retry until cache clearing/new session.
The sparse view remains an explicitly labelled temporary or capped fallback.
Snapshots share this startup policy synchronously, without any idle/background
worker. Their default camera covers the full image, rendering from native,
completed cache, or a clearly labelled sparse preview. Explicit `--region`
remains strict. The clock limit is cooperative between native reads, so a single
codec call can exceed it and snapshot output may vary with I/O performance.

`intensity_window.py`, `compositing.py`, `text_renderer.py`, and `text_image.py`
separate raw intensities, normalized RGB, character selection, and serialization.
Inputs are unchanged and retained outputs own their arrays. ASCII colored hue
normalization is a display operation, not source color normalization.

`viewer/` contains terminal controls, bindings, worker requests, and application
lifecycle. UI painting reuses prepared cell/style runs; it never decodes tiles.
The event loop owns UI state. A single display worker owns sampling/rendering,
with a latest-pending-request slot. There is no unbounded queue of old wheel events
waiting to become images. Accepted completed frames carry their generation number;
a stale generation cannot replace the current request's result.

## Local/remote resource boundary

`source_input.resolve_input()` owns the source lifetime. Local OME-Zarr directories
and HTTP(S)/S3 Zarr store roots stay lazy through Omeify's `OMEZarrReader`;
Zarr chunks are never predownloaded as one file. A non-Zarr HTTP(S)/S3 image,
TIFF, SVS or PDF is streamed into a bounded temporary file (128 MiB by default)
under its original extension for Aperio dispatch; URL query strings are never
used as filenames or display labels. The temporary file remains available
until the entire interactive viewer and PDF worker tree has stopped, then
is deleted. No cached credentials, on-disk image conversion, or downstream
raster decoder is introduced. S3 is an explicit `s3fs` optional extra.

`ImageDocument` treats remote Zarr roots as URIs, not local resolved paths,
and offers the same declared-series navigation used for TIFF. Local Zarr paths
are directories. The public `open_image()` and `view_file()` both resolve sources,
while direct already-resolved paths use the same reader/display implementations.
A local file's signed-inode safety checks and PDF text extraction stay bound
to its actual file path; remote Zarr has no local PDF source stamp.

Shifted Omeify `ImageLevel.offset_yx` grids cannot be correctly sampled by the
scale-only camera. For now `ViewInfo` excludes non-base levels whose offset
is nonzero. All normal, sparse and cached overview paths share that filtered
level list. Base pixels/annotation coordinates are unchanged. A future offset-
aware camera can restore those levels without guessing a transform.

## Ordinary-file ingress

`image_input.py` is deliberately a small, explicit front door, not a plugin
registry. TIFF and PDF signatures select their paths; within TIFF, `.svs`
(case-insensitive) selects Omeify's validated Aperio reader and other suffixes
retain the OME reader. No fallback on decoder failure is attempted. the remaining path uses
Pillow with a fixed raster-format allowlist. No decoder exception triggers a
fallback, and formats such as EPS cannot invoke converter subprocesses. The
Pillow and PDFium are both standard installation dependencies, but are
lazy-imported only for the relevant formats. Even `twhy.open_image` remains
importable without loading those decoders.

One selected raster frame is loaded, orientation-corrected, and composited over
a chosen opaque matte before reduction. Common display modes become RGB8;
16-bit scalar PNG retains uint16 intensity. ICC color conversion is out of scope.
The single-image `open_image(..., pdf_dpi=...)` operation remains a fixed-DPI
rasterization. All parent-process PDFium work, including import and native cleanup,
uses one lock. Unrelated PDFium callers in an embedding application must coordinate
their own native calls. RGB byte order is explicit and native bitmap pixels are
copied before their bitmap/page/document handles close.

Interactive PDFs open at min(144, max-DPI). After the first frame, independent
spawned processes call the same PDF rasterizer and pyramid builder for higher
resolutions. Only NumPy arrays cross private, per-job pipes; no native handles,
shared pool queue, temporary file or second renderer is introduced. At most two
processes run concurrently. Receiver threads keep large transfers/unpickling off
the event loop. Terminating an obsolete process discards its private pipe; all
receivers and processes are drained/joined before shutdown. `asyncio.TaskGroup`
waits for every child finalizer, including cancellation, rather than returning
when only the first cancelled child has finished.

`image_pyramid.py` performs file-free dyadic reduction through 1x1. Level zero is
an independent unchanged copy, and all retained levels are immutable. Float64
sums and finite counts propagate to the next reduction before dtype rounding;
odd edges are neither padded nor equally weighted against larger supports.
Explicit `ImageLevel.downsample_yx` values are powers of two, not ratios of rounded
array dimensions. Omeify borrows these owned arrays through `from_array(copy=False)`.
This eager ingress pyramid is distinct from the generic ViewSession's optional,
incrementally constructed display-overview cache.

This ingress intentionally pays the complete decode/build cost in RAM. Its
retained pyramid and transient sums/copies are outside the session preview-cache
and per-read budgets. No temporary TIFF or persistent cache exists. Array-image
references retain their arrays after close, following Omeify's standard ownership
contract; releasing the references releases this storage. CLI process exit also
releases it. OME-TIFF's existing read/cache/lifetime policy is unchanged.

## Document navigation and progressive source lifetimes

`--series` and the OME jump prompt are zero-based; PDF `--page` and its prompt are
one-based. PageUp/PageDown and brackets share the same document navigator; `p`
reuses numeric entry without stealing the channel number shortcuts or gamma's
`g` key. A clickable navigation bar shows the selection, count and PDF progress.
For OME sources, `d` and clickable Z/T/Series chips select the dimension for
brackets, PageUp/PageDown and `p`. Source Z/T axes come from `axis_info`, not the
normalized block shape, which can contain absent singleton axes. New pages/series
fit and initialize their own channels; Z/T steps preserve camera and display
settings. Raster frames remain startup-only.

The event loop owns the document cache and reference counts. `DocumentItem`
retains an open image independently for the active viewer, pending handoff, and
cache. Only the best completed pyramid per page is cached, with three pages by
default. Source swaps happen in the display pump, between completed reads. The old
ViewSession then closes and releases its active item. Creating a new session for
an upgrade prevents stale raw-preview cache reuse. No mutable source geometry or
private Omeify source/cache fields are used.

An upgrade scales the viewport by actual old/new raster extents on each axis,
preserving page-relative pixel-edge coordinates despite noninteger DPI ratios and
rounded dimensions. It never fits again just because more detail became ready.
If a deliberately small read budget rejects the unchanged field at that DPI,
the old source remains usable and the better pyramid stays cached. A later camera
or renderer change can retry the upgrade; identical repaints do not retry forever.
PDF `--region` coordinates are on the initial quick-preview grid even in a snapshot.

Requested navigation and displayed selection are distinct: the old page is never
relabeled as the new one while loading. Navigation retargets the one source-loader
thread instead of queuing every keypress. A finished obsolete load is released,
not displayed. Recoverable open errors keep the previous source. Old PDF refinement
and neighbor jobs are cancelled; a late lower-DPI result cannot downgrade the active
or cached page. The next/previous pages are prefetched only after current-page
refinement reaches its ceiling. Distant cached pages are pruned on navigation.

`--pdf-max-dpi` replaces the CLI `--pdf-dpi`; the default sequence is 144/300/600.
Custom limits append the exact requested ceiling to the standard lower stages.
Snapshots render the selected page directly at the ceiling, deterministically,
without processes or prefetch. The explicit Python `open_image(..., pdf_dpi=...)`
API continues to yield one stable, fixed-resolution image. `Viewer(session)`
continues to borrow that stable session; `view_file()` owns navigation lifetimes.

Process memory includes active/cached rasters, old/new source handoffs, reduction
scratch and pipe-transfer copies. Page count and small-preview bytes are different
budgets, neither a process-tree RSS limit. Quitting reaps refinement processes;
an in-flight parent quick-preview/TIFF read must finish before its image closes.
No work is started by importing the array renderer, and no PDF worker writes a
persistent image cache. Executable Python embeddings must use a main guard for
spawn, as the CLI module does.

## Shareable PNG clip export

The selection controller captures the already-rendered immutable
`TextImage`, not pixels from the original file, and does not include its visual
selection border. `png_clip.render_clip_png()` maps each `▀` directly to its
stored RGB foreground (upper half) and background (lower half). This yields a
shareable, exact-color 12x24-pixel tile for each selected terminal cell without
ANSI escape sequences, re-reading OME-TIFF tiles, or rasterizing a PDF again.
Braille is rendered geometrically; other glyphs use available local fonts and
are therefore typographically approximate outside half-block mode. PNG output
has a separate output-pixel safety limit.

`image_clip` writes binary PNGs atomically using the text-clip module's destination
protections. The independent **i / I** copy/save bindings use the existing
selection lifecycle and one clip-worker executor. Native image clipboard copying
is attempted locally using platform helpers; OSC 52 cannot carry binary PNG
clipboard content, so unsupported/remote sessions receive an explicit file-save
fallback message. Mac helper transfers bytes from a promptly deleted temporary
PNG file because AppleScript's PNG clipboard type reads file data; this temporary
file is unrelated to PDF or image pyramid caches. Neither helper reads the
clipboard or sends image data over the network.

## Structured text rendering

`TextRenderer` defaults to `detail`; `shape` and `simple` are the other text modes.
`ascii` is an input alias for `simple`. `blocks` retains the original two-color
half-block path. Simple and blocks retain their previous numerical algorithms.

`renderer.sample_shape()` is the planning boundary: detail and shape ask for
8-by-4 display samples per terminal cell. The CLI and worker already use that
public contract, so they preserve subcell structure through regional reading and
raw resampling, before windowing and composition. This may select a finer pyramid
level; it does not bypass the source-sample budget or create a second decoder.
Library callers must use that contract too, rather than passing cell dimensions
as if all renderers used one sample per cell.

`structured_rendering.py` consumes normalized display samples and emits a normal
`TextImage`. Detail addresses a 4-by-2 Braille dot grid from the 8-by-4 samples.
It uses mild local sharpening, an ordered rounding rule for each cell's total dot
count, and ranks addressed intensities to select dot positions. A small fixed tie
preference balances nearly equal samples. Zero/absent positions cannot receive
ink solely through the tie preference. The bit order follows Unicode's dot
numbering, including the bottom-left/bottom-right bits 6 and 7.

Shape uses a relief-style intensity transform and compares centered, normalized
patches to the hand-authored stroke descriptors in `glyph_atlas.py`, balancing
spatial correspondence against tonal error. Low-variation cells use the tonal
anchors instead of arbitrary letters. These masks are geometric approximations,
not terminal-font rasters or extracted font data. There is no font dependency.

Normalized convolution excludes missing coverage from neighborhood statistics;
missing samples do not become false dark boundaries. Candidate descriptors are
also masked and renormalized on partial cells. Shape matching uses batches of at
most 256 cells; it never creates a whole-slide candidate tensor. Structured output
grids have a separate 4,194,304-position cap checked before resampling. Existing
sample-count and cache budgets remain distinct from a process-RSS limit.

Both structured modes use foreground-only color. Their UTF-8 characters still
carry the structure in plain snapshots; independent background colors remain
exclusive to explicit blocks mode. All modes share `TextImage`, terminal runs,
atomic snapshot publication, and worker lifetime handling. There is no browser,
model inference, semantic description, random rendering, or persistent state.
The ordered pattern is screen-grid anchored, not motion-compensated.

The UI's `m` cycles detail/shape/simple/blocks (omitting blocks without color).
`b` toggles the original half-block preview and restores the previous text/color
settings. Color toggling preserves a text mode. Switching modes never requests an
automatic contrast reset: existing per-channel windows stay locked. Detail and
shape request identical sampling grids and share cached previews for a view.

## Terminal capability policy

The CLI's `--mode auto` is deliberately a *frontend policy*, not another glyph
algorithm. `terminal_capabilities.py` chooses the original blocks renderer for
interactive Unicode-capable terminals whose prompt_toolkit color depth is at
least 256 colors, and simple for limited terminal/encoding capabilities or
explicit no-color. The selector respects the same color-depth precedence as the
viewer (`NO_COLOR`, `PROMPT_TOOLKIT_COLOR_DEPTH`, `COLORTERM`, toolkit default).
For an advertised one-bit output or `NO_COLOR=1`, the CLI also initializes
the actual renderer in monochrome, so `m` skips invisible half-blocks instead
of merely suppressing color escape sequences. Explicit `--color` overrides
this renderer default. No terminal escape sequence is sent to probe capability.
Font coverage itself cannot be verified; users can always force a mode. The viewer status shows the
resolved renderer rather than claiming a font was tested.

Snapshots have a different output contract: auto + no ANSI emits portable simple
text, while auto + explicit ANSI emits truecolor blocks. The array-level
`TextRenderer` retains its context-independent `detail` default. Explicit modes,
`sample_shape()`, and their numerical rendering are unaffected by auto selection.

## Thread and resource contract

Keep the Omeify image and `ViewSession` contexts open for `Viewer.run()`. The viewer
waits for an in-flight read on exit; cancellation does not pretend to interrupt a
native TIFF codec. Session methods serialize reads and session close through an RLock.
A session borrows a stable image: do not mutate its pixels or concurrently close
it. A new image lifetime requires a new ViewSession, whose preview cache belongs
to the original observation. Closing the display does not close the caller's image.
A session rejects access after its source is closed and reopened, including cache hits.

The provider's cache is retained on channel/level and Z/T switches. Omeify owns
shared native-block caching and its aggregate budget. twhy's own preview LRU
can retain multiple channels/viewports within one immutable plane session.
A new plane receives a new ViewSession; its display cache cannot reuse another
plane's pixels. Changing intensity windows does not change preview-cache keys.

There is no on-disk cache or implicitly written user configuration. Errors do not
fall back to another decoder. Snapshot output is independent of terminal state;
file publication is atomic within the destination filesystem, with exclusive
publication for `--no-overwrite`.

## Deliberate future work, not hidden partial implementations

The upgraded Omeify source cache supplies shared decoded-block reuse. Further
profiling should precede enabling its optional predictive reads; no second raw
tile cache is added here. Render-time optimizations should be compared
with the exact rectangle-area oracle in tests.

More glyph modes, overlays, and other terminal frontends should share `TextImage`
and the normalized image pipeline, not add independent contrast semantics. Further vendor formats should only be added after their reader-level
region/pyramid contracts are verified. Input conversion support alone is not evidence of interactive read support.

## Rectangle selection and clip delivery

`TextImage.crop(y0, y1, x0, x1)` is a file-free, framework-free exact copy of a
nonempty half-open cell rectangle, including its foreground/background arrays.
It never re-renders or includes the selection overlay. `viewer/selection.py`
contains the cell cursor/anchor and outline painting; `viewer/clipping.py` owns
selection lifecycle and explicit delivery. No alternate image reader, additional
full-image raster, GUI clipboard dependency, or change to ViewSession is added.

Selection starts only on a completed current frame. Its small TextImage and
pixel-edge viewport are frozen together; camera/style/navigation controls are
inactive. The display pump and DocumentNavigation defer source handoffs while
selecting, while the normal PDF cache can accept completed refinement jobs.
Ending selection wakes the pump, allowing the best pending source to be installed.
Canvas resize cancels the rectangle; path entry reuses a footer row and does not
change canvas geometry. Mouse release on a toolbar button is not treated as Copy
unless the press also began on that button.

Native PDF text copying maps selected terminal-cell edges into the displayed
base raster, clips letterboxing, and uses FPDF_DeviceToPage's affine transform
with the actual raster dimensions and the same additional rotation (zero) used
by the PDF renderer. Rotation and nonzero/cropped page origins are therefore not
approximated by a hand-written y-flip or assumed DPI ratio. `pdf_text.py` opens
native text handles under PDF_LOCK, extracts bounded text and closes them before
return. It does not render pixels, run OCR, reconstruct paragraphs or infer words
from the terminal glyphs. An input-file stamp guards against copying text from a
PDF replaced/modified on disk after opening.

A single lazy clip executor performs extraction, optional local helper calls and
atomic file writes. Each accepted operation captures immutable clip content and
page coordinates before submission, so later changes cannot alter that clip.
Repeated copy/save keys while busy do not create a queue. Shutdown joins accepted
work; OSC output is emitted only from the event loop while the application is
running, using its Output rather than global stdout. There are no clipboard-read
queries or automatic clipboard/file writes on selection.

`text_clip.py` implements explicit UTF-8 file publication and clipboard transport.
Auto optionally tries a local clipboard helper, otherwise uses ordinary OSC 52.
SSH/multiplexers use OSC directly rather than writing a remote desktop clipboard.
It does not change terminal security preferences or enable tmux passthrough.
OSC sends are unacknowledged and the status says so. The 64 KiB raw UTF-8 payload
limit is an application safeguard, not a universal terminal capability promise.
Clipboard failure cannot erase an already-successful file save. Input aliases,
output symlinks and nonregular files are rejected before and immediately before
atomic publication; no-overwrite uses exclusive hard-link publication.

The existing PDF process finalizer is additionally shielded against cancellation
arriving during its normal successful cleanup. Awaited process joins and pipe
reception must complete even after repeated cancellation; merely awaiting a
TaskGroup is insufficient when a child's own finalizer was interrupted.


## Anonymous multi-area selection and shared export

`annotation_identity.py` creates UUIDv4 IDs with stdlib `uuid.uuid4` and short
coolname labels. This module imports coolname lazily at first naming use, not
when the numerical renderer is imported. IDs have no path, filename, timestamp,
image-content or host input. An event-loop-owned factory rejects generated-name
collisions within one Viewer; per-area immutable identity records retain the ID
when their user-editable name changes. No automatic classification is generated.

`viewer/selection_set.py` owns multiple rectangle/polygon editors over the same
frozen TextImage. One area is active for editing/naming; all nonempty areas are
included in export. Adding or changing tools retains previous areas. Areas may
be cycled or deleted without starting another image read. Empty drafts are not
features; unfinished or invalid polygons produce an error, not a partial export.
The existing freeze, resize invalidation and deferred PDF handoff rules now apply
to the whole collection. Collections do not span cameras, PDF pages or OME series.

`selection_geometry.py` is file-free: immutable rings, simple-ring validation,
bounding rectangles and union masks. Rectangle boundaries use cell edges;
polygon checkpoints use cell centers. Cell-center masks choose text glyphs;
output-pixel-center masks retain subcell polygon edges in PNGs. Union operations
preserve gaps, overlap and relative placement without duplicating source content.
Mask computation is row-chunked. Geometry is captured before dispatch, not read
from mutable editors while the export worker is running.

`TextImage(mask=...)` blanks excluded characters, erases their retained RGB
values, and emits default-style spaces in ANSI runs. Unmasked TextImage behavior
and existing numerical renderer outputs remain unchanged. PNG draws the unmasked
bounding frame, then applies the finer geometric union mask and image-boundary
mask. It writes RGBA with all four bytes zero outside the mask; alpha does not
conceal an excluded RGB payload. These are terminal-artwork PNGs, not original
source-resolution crops. Input alpha already composited by ingress is not recovered.

`ClipController` uses one shared worker/delivery path for text, ANSI, PNG and
GeoJSON in either tool. Each accepted job captures immutable area identities,
geometry, cells, source stamp and destination settings on the UI thread. Renaming,
adding or ending a selection cannot change an in-flight export. Native PDF words
remain a single-rectangle operation; polygon and multi-area text are explicitly
labelled screen artwork rather than extracting the union's larger PDF bounding box.

GeoJSON is constructed from an allowlisted viewer record: feature ID, geometry,
name, name_generated and selection_type. No image descriptor is merged into its
properties. Source paths stay internal for file protection and PDF extraction.
Generic suggested output filenames likewise avoid source metadata. The public
geometry helper still accepts an explicitly supplied properties dictionary;
callers are responsible for any metadata they deliberately supply themselves.
Image-edge intersection validates the resulting single ring; a disconnected
concave intersection is rejected with a request to select its parts separately.
No new geometry dependency is introduced.

The channel list has focus-specific PageUp/PageDown and Home/End handling;
canvas document navigation and bracket shortcuts are unchanged. Focus changes
alone do not sample pixels. Enter solos any focused channel. Adaptive sidebar
content reserves more rows for channels rather than increasing sidebar width.
`ModeNavigation` remembers the active `m` artwork renderer
(detail/shape/simple/blocks), its **independent color preference**, and a
separate strictly monochrome `M` ASCII ramp index. `m` restores or advances
artwork; when color is off it cycles only detail/shape/simple and skips blocks.
`M` restores or advances classic/fine/bold ASCII variants of the existing simple
renderer, without changing the `m` color preference. `t` toggles that preference;
while `M` is active, the visible ASCII remains unstyled. `b` temporarily renders
colored half-blocks and can restore an exact monochrome artwork or ASCII style.
Switching families preserves the last mode in each, with no one-shot restore flag. In selection, a cloned navigator and style-keyed cached frames
rerender existing ViewSamples without another source read, leaving cell geometry
and region identities/masks untouched. The viewer's normal style is restored after
selection. Full-terminal
name/file prompts use a conditional floating entry row, avoiding selection loss
from a canvas resize. The normal viewer gains no additional UI rows.


## Session-local channel color controls (October 24, 2026)

`channel_colors.py` centralizes the existing exact floating-point default palette,
strict hex/name/default parsing, and attaching colors to prepared `ChannelStyle`
records. `Viewer` owns colors indexed by the full source channel list, separately
from its intensity windows. The same override map enters the CLI snapshot and
file-viewer paths. It does not mutate Omeify image metadata, pixels, or calibration,
and introduces no dependency or alternative renderer.

`h` shares the existing entry widget and cancellation behavior. It can edit a
hidden/unread intensity channel without forcing a window estimate or visibility
change. RGB input rejects pseudocolor overrides. An unchanged prefilled hex entry
preserves the original floating-point color rather than quantizing it on Enter;
`default` also restores that exact value. Input errors cannot partially update a
palette. A color edit captures its source session/channel, so a pending series
handoff cannot apply an old edit to a different source. Series changes initialize
a fresh palette alongside the existing fresh windows.

Every `FrameRequest` snapshots immutable colors, not a borrowed mutable UI list.
For a color-only update it may also retain the already-displayed `ViewSamples`.
The worker recomputes the metadata-only read plan and reuses those samples only
when the plans match exactly. Otherwise it performs the ordinary budgeted read.
This avoids extra pixel reads even with the preview LRU disabled, without reusing
an old view after a pan, channel change, canvas resize, or source replacement.
Normal camera/mode/overview scheduling and stale-generation rejection remain in
place. Frozen selection renderer previews use the same palette; ANSI/PNG export
continues to serialize the actual frozen artwork, not source metadata.

The sidebar's right-aligned swatches use terminal-cell widths, including wide
Unicode channel labels. Clicking a swatch edits rather than toggles; the rest of
the row retains visibility toggling. The focused hue/color row is clickable too.
At short heights channel-list paging still reserves at least one visible channel;
the `h` key remains available even when its detail row or the sidebar is hidden.


## Z/T document lifetimes

`ome_navigation.py` is a frontend ownership adapter, not a decoder. A
reference-counted `DatasetHandle` retains the real public Omeify dataset. The
active ImageDocument and each live DocumentItem hold independent references.
Items close their plane Image before releasing their owner. Discarding a stale
series load cannot replace or evict the displayed series' source. New series
are opened on the one source-loader thread; the accepted handle becomes current
only during the between-reads handoff. Shutdown stops the loader, joins display
work, and then releases the active image and owner.

ImageDataset currently lacks public series collection descriptors. twhy performs
one separate metadata-only public `TiffInspector`/`ZarrInspector` discovery at
initialization to obtain the series count. This may repeat startup metadata I/O;
it is never performed for Z/T stepping. No private Omeify fields, TIFF XML or NGFF
parsers are used. A future public collection descriptor can eliminate that extra
startup discovery without changing the navigation model.

The request target includes series, Z and T plus a monotonically increasing
navigation epoch. Source-loader and render completions are checked independently.
The displayed item and the requested item remain distinct while loading. A plane
handoff preserves the exact camera and windows, drops stale display samples, and
requests one new frame without fitting or a timed startup-overview scan. Ordinary
bounded idle overview work remains available for that selected plane. Selections
freeze the displayed observation and all dimensional navigation.

Automatic resolution selection consumes only the plane Image's compatible XY
levels. A stored Z-reduced level is not treated as another resolution of that
section. No projection, interpolation along Z, time playback or coarse-volume UI
is added. Those are twhy presentation choices, not policies inserted into Omeify.
Omeify prefetch is left disabled until real navigation measurements justify it.

The ordinary stable-image Python `open_image()` remains strict about non-singleton
axes. CLI snapshots explicitly opt into `first_plane=True`, matching interactive
initial selection: zero for omitted present axes, None for absent axes. Explicit
indices are validated rather than clamped. Anonymous GeoJSON remains unchanged;
Z/T context must be recorded separately when consuming an exported region.
