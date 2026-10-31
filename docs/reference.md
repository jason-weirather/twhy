# twhy

A whole slide pathology image viewer in text; because sometimes the answer to “why is this in the terminal?” is “yes.”

`twhy` is a library-first image-to-text renderer and a full-screen viewer for
OME-TIFF, Aperio SVS, OME-Zarr, ordinary raster images, and PDF pages. Local
files and bounded HTTP(S)/S3 resources use the same interface; OME-Zarr reads
only the requested metadata and encoded chunks.
The CLI defaults to **auto**: two-color Unicode half-blocks when the terminal
supports them, otherwise portable **simple** ASCII. **Detail** uses spatial Braille;
**shape** emphasizes typographic strokes and texture. Explicit **blocks** remains
available, and the array renderer's library default remains detail.
No terminal bitmap protocol, browser, image server, X11, or GPU is required.

This is an early exploratory viewer, not a diagnostic display or a color-managed
replacement for a microscopy workstation. It is useful for navigation and visual
checks, not pixel measurements from the rendered text.

## Install

Python **3.11+**. The **PyPI distribution**, terminal command, and Python import
are all named **`twhy`**. This branch requires `omeify>=0.23.0` and the dataset API from the updated
`z_t_support` checkout at `6e926f2`. Install that source revision in the same
environment; the numerical version alone does not certify a branch revision.
[Z/T installation and validation](z_t_support.md).

```bash
python -m pip install twhy          # all local formats, including PDF
python -m pip install 'twhy[s3]'   # optionally enable native S3 reads

twhy --version
twhy photograph.png
```

For a **CLI-only installation**, `pipx` or `uv tool` is a good fit: either gives
`twhy` its own Python environment rather than changing NumPy, Numba, or other
packages in an existing analysis environment (once the distribution is published):

```bash
pipx install twhy
# Or, if you use uv:
uv tool install twhy
```

When installing `twhy` into a shared Python environment, its NumPy requirement
accepts existing NumPy 1.26.4 and 2.0.x installations, as well as newer NumPy 2.x.
There is no reason for twhy itself to demand NumPy 2.1 or upgrade a compatible
installation. Other installed packages can have their own constraints, so verify
shared environments with `python -m pip check` after installing.

From this source checkout:

```bash
mamba env create -f environment.yml
mamba activate twhy_env
python -m pip install -e '.[dev]'
python -m pip check
```

To install the **CLI directly from this checkout** without touching the active
analysis environment, use either isolated tool installer here:

```bash
pipx install --editable .
# Or, if you use uv:
uv tool install --editable .
```

Editable installs refer to this checkout, so keep it in place.

Pillow supplies common image codecs and pypdfium2 supplies PDF support in every
standard install. Both decoders are imported only when needed. OME-Zarr is handled
by Omeify's normal Zarr/fsspec dependencies. S3 access remains an **optional**
s3fs dependency and uses the standard AWS credential chain; access keys never
belong in image URLs. No graphics server or GPU is needed.

## OME-Zarr, remote images, SVS, and PDF pages

```bash
twhy slide.svs                            # Aperio whole-slide RGB, stored pyramid
twhy slide.SVS --snapshot --ansi -o slide.ansi

twhy photograph.jpg
twhy screenshot.png
twhy illustration.webp
twhy icon.png --background black          # transparent pixels default to white

twhy document.pdf                         # quick 144 DPI, then 300 and 600 DPI
twhy document.pdf --page 3                 # PDF pages are ONE-based
twhy document.pdf --pdf-max-dpi 144        # cap detail; no higher-resolution jobs
twhy document.pdf --pdf-max-dpi 450        # 144 -> 300 -> 450 DPI
twhy document.pdf --pdf-max-dpi 1200       # 144 -> 300 -> 600 -> 1200 DPI
twhy document.pdf --pdf-cache-pages 1      # current page only; no neighbor prefetch

twhy animation.gif --frame 5               # raster frames are ZERO-based
twhy illustration.webp --snapshot --ansi -o preview.ansi
```

### Local and remote inputs

```bash
# Native OME-Zarr directory (NGFF 0.4, 0.5 or 0.6), regional reads:
twhy /data/tonsil.ome.zarr --channel 0 --channel 2

# HTTP(S) OME-Zarr store ROOT (serves metadata/chunks, not a ZIP):
twhy 'https://images.example.org/tonsil.ome.zarr' --channel 0

# S3 OME-Zarr; install twhy[s3] and configure AWS credentials/role:
twhy 's3://my-bucket/tonsil.ome.zarr' --channel 1
# For an anonymously readable S3 bucket:
twhy 's3://public-bucket/tonsil.ome.zarr' --s3-anonymous

# Local S3-compatible service (e.g. MinIO):
twhy 's3://local-bucket/demo.ome.zarr' --s3-endpoint-url http://localhost:9000

# An HTTP(S)/S3 ordinary image or PDF is boundedly downloaded once, then decoded:
twhy 'https://images.example.org/example.png'
twhy 's3://local-bucket/book.pdf' --page 2

# Explicit store type for an extensionless HTTP(S)/S3 Zarr root:
twhy 'https://images.example.org/datasets/123' --input-format zarr

# Explicit plane/group for a multidimensional/collection Zarr:
twhy /data/experiment.zarr --group A/1/0 --z-index 2 --t-index 0
```

**Remote single files:** by default, only the first **128 MiB** is permitted.
`--max-remote-mib 512` explicitly raises the limit, including for remote PDF,
OME-TIFF, and SVS files. The file is staged in a temporary directory, **once
for an interactive session**, and removed on exit after all PDF workers have
stopped. Downloads have a finite timeout; a remote TIFF/SVS is not a streaming
whole-slide reader, even if its local form supports pyramidal region access.
Local files are not restricted by this byte limit. Remote Zarr bypasses the
whole-file limit but still consumes per-chunk requests and storage-provider
charges; existing render and overview budgets still apply. The download cap is
**not** a cap on decoded image/PDF RAM.

For S3, `--s3-endpoint-url` takes a plain HTTP(S) origin (or set
`AWS_ENDPOINT_URL_S3`). `AWS_PROFILE`, IAM roles, default credentials, and
public anonymous access are handled by the standard s3fs credential configuration.
Add `--s3-anonymous` for public, unsigned S3 reads. Do not embed keys into URLs. HTTP single-file URLs may contain signed query
parameters; they are never shown in the title or stored with clips. OME-Zarr
store roots must not contain query strings and should expose consistent objects;
remote stores are read-only. HTTP(S) servers require ordinary GET access to
metadata/chunk paths (and byte-range support for sharded input).

Local/remote Zarr keeps TIFF-style **zero-based series, Z and T navigation**.
`--group` chooses an image subtree. CLI and interactive opening choose middle Z (`size // 2`) and T=0
for unspecified axes that exist. Explicit invalid indices, including an
index for an absent axis, fail. The fixed-image Python `open_image()` helper keeps
strict explicit-selection behavior unless `first_plane=True` is requested.
Categorical label visualization remains unsupported. For pyramid levels with
nonzero pixel-edge offsets, twhy currently **skips the shifted level** and
uses an aligned one rather than silently misplacing tissue and GeoJSON positions.
This can make some Zarr views slower. The base level always remains available.

These inputs share the existing wheel/keyboard zoom, pan, contrast, rendering
modes, sidebar, and snapshot workflow. `auto` still chooses color half-blocks on
capable terminals and simple text otherwise. There is no second viewer.

| Input | Behavior in this pass |
|---|---|
| OME-TIFF | Persistent Omeify dataset, immutable Z/T plane Images and series navigation; remote files download under the explicit cap. |
| OME-Zarr | Omeify 0.4/0.5/0.6 datasets: local/HTTP(S)/S3, regional chunks, channels, series and Z/T; shifted XY levels are skipped. |
| Aperio SVS (`.svs`, case-insensitive) | Omeify AperioSVSReader, native RGB and supplied pyramid, regional decoding; optional bounded runtime overview cache. |
| PNG, JPEG/JPG, WebP, BMP, TGA | Decode once; retain the base raster and an in-memory pyramid. |
| GIF, APNG, animated WebP | Frame 0 by default, or select `--frame N`; no animation playback. |
| ICO | View the decoder's default icon representation. |
| PPM, PGM, PBM | Ordinary portable raster formats through Pillow. |
| PDF (standard install) | Navigate pages; quick RGB preview followed by sharper, RAM-only pyramids. |

An SVS is one logical RGB channel, not three independent stain channels.
Omeify reads Aperio `MPP` calibration when available and exposes stored reduced
levels. The `--series` control can also visit associated series (for example a
thumbnail) when the reader supports their pixel layout. GeoJSON coordinates
remain relative to the selected series' own base pixel grid.

OME-Zarr is recognized as a local store directory (containing NGFF/Zarr root
metadata, or named `.zarr`) or by the `.zarr` suffix of a remote URL. For other
remote Zarr store names, specify `--input-format zarr`. Ordinary remote files
are classified from their downloaded signature, not their suffix.
The file signature first distinguishes TIFF, PDF, and raster data. Within TIFF,
the `.svs` suffix selects Omeify's Aperio reader, which validates the actual SVS
format; other TIFFs continue through Omeify's OME-TIFF reader. Renaming an OME-TIFF
to `.svs` does not make it valid SVS, and an SVS renamed `.tif` is not automatically
detected. Unsupported formats fail explicitly. **Other non-OME TIFF, SVG,
EPS/PostScript, HEIC/AVIF, JPEG 2000, and raw
camera formats are deferred.** In particular, an OME-TIFF error never falls
through to Pillow, and no EPS plugin may invoke an external converter.

Ordinary RGB, palette, CMYK, bilevel, and 8-bit grayscale images become one RGB
logical channel. EXIF orientation is applied before constructing the pyramid.
Alpha and palette/color-key transparency are composited onto white, or black
with `--background black`, before downsampling. The terminal's letterbox remains
black; this option changes the image matte, not the terminal theme. Basic CMYK
conversion is not ICC-managed color. RGB previews use Pillow's decoded 8-bit
samples, including for higher-bit-depth RGB PNGs; this is not a lossless export
or a color-managed workstation. Scalar 16-bit PNG values are retained as uint16,
with the existing intensity-channel contrast controls rather than clipping to 255.

### Page, series, Z and T navigation

**`d`** cycles the available navigation dimensions: Z, T, Series. Click a
navigation-bar dimension to select it directly; a star marks the active dimension.
Z is initially active when it has multiple planes, otherwise T, otherwise Series.
A PDF keeps its Page dimension. **PageDown / `]`** goes forward;
**PageUp / `[`** goes back. Press **`p`**, type an index for the active dimension,
and press **Enter** to jump directly. Escape or Ctrl-C cancels entry;
invalid numbers stay in the editor. The navigation bar also has clickable
previous, next and go-to controls, and shows the current page and document count.
The mouse wheel over the image remains zoom, not page turning.

The same controls switch **OME-TIFF and SVS series**, if provided by the reader.
PDF page numbers are **one-based**; TIFF/SVS series indices remain
**zero-based**, matching `--page` and `--series`.
The limits are shown in the jump prompt. Raster frames remain startup-only via
`--frame`, with no animation playback or frame-navigation UI in this pass.

A Z/T step preserves the exact base-pixel camera, selected channels, focused
channel, pseudocolors, contrast windows, gamma and rendering mode. It uses another
immutable plane Image from the same source session, not a reopened file/store.
Rapid requests coalesce, old frames keep their old labels while loading, and
obsolete completions cannot overwrite the latest request. New plane handoffs
wait for any in-flight read and do not trigger another timed startup scan.

Only the selected Image's exact-section pyramid participates in automatic zoom.
Native XYZ levels that change Z sampling are not substituted for that optical
section. Such inputs remain readable at their base and compatible XY levels;
coarse-volume viewing is not implemented in this pass.

A new page/series fits the display. PDF contrast, gamma and rendering mode remain
selected as you turn pages. A new OME series resets channel selection to 0 and
initializes its own intensity windows; RGB/intensity default density follows the
new series unless explicitly overridden. Opening an unsupported series reports
an error and retains the previous view. OME reads still use only Omeify;
small, budgeted native-level overview scans may now run before the first frame,
with larger eligible scans continuing incrementally during idle time.

### Progressive PDF detail

The default **`--pdf-max-dpi` is 600**. First, the selected page opens at 144 DPI
(or the ceiling itself when lower than 144). Once its first frame reaches the UI,
up to **two spawned Python processes** independently render and build the 300 and
600 DPI pyramids. These are real new PDF rasterizations, not enlarged versions
of the 144 DPI preview. PDFium is not thread-safe, so native refinement work is
isolated by process rather than concurrent threads sharing the PDF library.
No converter executable or additional dependency is involved.

Higher-detail results automatically replace the current source **without moving
the page-relative field of view or resetting contrast**. Completed sources are
swapped only between display reads. A late 300 DPI result never replaces a ready
600 DPI image. The title/bar show available detail, the configured ceiling, and
current builds. Zooming can temporarily magnify the quick preview while sharper
content is still being prepared; terminal character resolution remains a separate
limit. A tight custom read budget postpones an upgrade rather than moving the
camera; a subsequent zoom can use the cached detail.

The stages are 144, 300 and 600 DPI below the chosen limit, followed by the exact
limit. For example, 200 uses 144/200, 450 uses 144/300/450, and 1200 uses
144/300/600/1200. There are never more than two active refinement/prefetch processes.
The old **`--pdf-dpi` CLI option is removed**. The single-image Python
`open_image(..., pdf_dpi=...)` API remains an explicit fixed-resolution operation.

Only after current-page refinement finishes successfully does twhy prepare the
next and previous pages. The default RAM cache holds **up to three pages**, with
only the sharpest completed pyramid for each. Moving away prunes distant pages,
cancels obsolete refinement/prefetch jobs, and prioritizes the new page. Cached
pages open at their best ready resolution. `--pdf-cache-pages 1` disables neighbor
prefetch; a limit of 2 prefetches one neighbor, favoring the next page when available. This
page-count limit is separate from `--cache-mib`, which still bounds small resampled
previews, not decoded pages or construction scratch. No persistent image cache is written (temporary downloads of remote PDFs are
removed after the viewing session).

Recoverable high-detail failures leave the usable lower-resolution view and show
an error. Quitting cancels and reaps the PDF processes and drains their private
pipes. An already-running quick-preview or TIFF read in the source-loader thread
must finish before its resources can close, just as display reads do.

Snapshots are deterministic: they render only the selected page, directly at the
maximum DPI, with no workers or neighbor prefetch. `--pdf-cache-pages` applies only
to interactive PDF viewing. PDF `--region` coordinates use the initial preview
pixel grid (up to 144 DPI), also for snapshots, and are mapped to the final raster.
PDF DPI does not invent microscopy calibration. Page rotation, rendered annotations,
and available form appearances are included. Rectangle text copying is described below. Text search, password entry, PDF editing
and interactive form filling are not implemented.

### Selection: text, ANSI, PNG and GeoJSON

Press **`s`** for rectangles or **`v`** for polygons, or use the footer buttons. Drag a rectangle with the
left mouse button. The highlighted outline and cursor are UI overlays only:
copying never includes the border, sidebar, title, or status text.

For keyboard selection, use the arrows to position the cursor, press **Space**
to anchor the first corner, then use the arrows to extend the box. **Shift+arrows**
can also start/extend a box, and **Tab** swaps the active corner. **Home/End** move
to the canvas's first/last cell. Both endpoint cells are included; rectangles
work in either drag direction. The sidebar and status show the current controls,
text source, active area, and its name. Polygon checkpoints use terminal-cell centers;
click the first point or press **Enter** to close. **Tab** reopens a closed polygon,
then removes its most recent vertex.

| While selecting | Action |
|---|---|
| `y` / `Y` | Copy / save text from **all** selected areas. Ctrl-C also copies; Enter first closes an open polygon, otherwise copies text. |
| `i` / `I` | Copy / save one PNG of the selected artwork, with transparent gaps. |
| `t` / `T` | Copy / save terminal ANSI artwork; unselected cells become unstyled spaces. |
| `j` / `J` | Copy / save one GeoJSON FeatureCollection with a separate feature per area. |
| `a` | Keep the current area and start another with the same tool. |
| `s` / `v` | Switch to the other shape tool, retaining existing areas. The current tool's key exits selection. |
| `[` / `]`, or PageUp / PageDown | Activate the previous / next area. |
| `n`; Delete | Rename / remove the active area. |
| `m` / `M` | Resume/cycle artwork (colored or monochrome) or enter/cycle strict ASCII. Uses cached samples without moving any area. |
| Escape; **Esc** button | Clear this selection session and resume viewing. |
| `q` or Ctrl-Q | Quit. Ctrl-C during a path/numeric prompt cancels only that prompt. |

The displayed frame is **frozen while selecting**. Zoom, pan, channel changes,
and page/series/Z/T navigation are inactive until you finish selection. PDF workers
may finish and cache better detail, but source replacement waits until selection
ends. This keeps the copied rectangle attached to precisely what you selected.
All areas share this one frozen view. They do not span pages, series, Z/T planes or camera changes.
A terminal/canvas resize clears the whole set rather than exporting shifted cells. Save prompts reuse a footer row, so opening a prompt does not
resize the image or shift the selection. In full-terminal mode, entry overlays the
bottom row instead. No additional PDF raster is created
for selection; it borrows the already-rendered, small immutable TextImage.

**There are two kinds of text.** With the default `--clip-source auto`, file-backed
PDF viewing copies the PDF's **embedded words** for a single rectangle.
Polygon and multi-area selections instead copy masked **screen characters**;
the status explicitly says `screen text`. This avoids including PDF words from
unselected parts of a larger bounding box. Selecting an ASCII preview with **M**
also explicitly selects screen text. No polygon-filtered PDF text extraction or
OCR is implemented. For single-rectangle embedded extraction, twhy maps the
selected cell edges through the frozen viewport to the PDF page using PDFium's
own coordinate transform, including page rotation and CropBox offsets. The
current DPI does not limit text extraction. This uses the standard PDFium
dependency, with native handles serialized under the existing PDF lock and no bitmap
allocation. Text order, spacing, ligatures, and Unicode mappings follow the PDF
text layer/PDFium; this is not paragraph reconstruction or table extraction.
Invisible/OCR text layers can differ from what the page appears to show. This
feature is not a redaction or visibility-verification tool.

For PNG/JPEG/WebP/OME-TIFF and borrowed-image `Viewer(session)`, text means the
**literal rendered terminal characters**, with exact rectangular whitespace.
No OCR runs on images or scanned PDF pages. If a PDF rectangle has no embedded
text, copying reports that fact and leaves both the clipboard and output file
untouched; it does not silently substitute block characters. Use
`--clip-source screen` to deliberately copy terminal glyphs instead of PDF words.
**`i`/`I` always export screen artwork as an image**, regardless of input type or text layer.
For multiple areas, one bounding rectangle preserves their original relative positions.
Text/ANSI keeps cells whose centers are in any area and space-pads the rest;
PNG masks at output-pixel resolution for subcell polygon edges. Overlaps are
included once in the artwork, but remain separate named GeoJSON features.
An untouched new-area cursor is ignored; an unfinished polygon blocks export
until it is closed or removed. Up to 256 areas can be selected in one view.
`t`/`T` export screen artwork as terminal ANSI regardless of input type.

Plain-text copying does not preserve colors. This matters especially in `blocks`
mode, where much of the picture lives in the foreground/background colors, not
in the repeated `▀` glyph. ANSI clips preserve the same character and color
arrays without re-rendering. They are raw escape-coded UTF-8 text, **not** an
image or rich HTML/RTF clipboard format; ordinary editors may show escape codes.
A supporting terminal can display a saved trusted clip with `cat detail.ansi`.

**For Discord or other ordinary chat applications, use PNG, not ANSI.** The `▀`
block combines two independent terminal RGB colors; pasting the glyphs or their
ANSI escape codes into Discord loses that picture. **`i`** renders a PNG from the
frozen text-cell grid and tries to place image data on your local clipboard.
**`I`** writes the PNG to a file for drag-and-drop/upload. The half-block export
reproduces exact RGB upper and lower halves without fonts or a second image decode;
detail/shape/simple modes use geometric Braille dots or available system fonts,
so their glyph appearance can differ from the terminal. The copied PNG does not
include selection outlines, names, title, help, or UI controls. It is not OCR.
PNG output is RGBA: outside the union and outside image bounds, alpha **and RGB**
are zero. It does not retain invisible excluded image colors. Black pixels and
blank glyphs inside selected image areas stay opaque. This is selection
transparency, not restoration of an input PNG's already-composited alpha.

Image copy uses macOS `osascript`, Wayland `wl-copy`, X11 `xclip`, or Windows
PowerShell if available. These are optional local OS helpers and no new Python
packages are required. **OSC 52 is text-only**, so `--clipboard osc52`, SSH,
and tmux cannot promise image clipboard copying. In those cases, press **`I`**
and share the saved PNG from a local machine. Clipboard acceptance by Discord
and particular desktops has not been tested on all platforms.

```bash
twhy document.pdf                          # s, drag, y: copy embedded words
twhy document.pdf --output-text-clip excerpt.txt

twhy document.pdf --clipboard off --output-text-clip excerpt.txt
# s, drag, y or Y: file only; no clipboard access

twhy photograph.jpg --output-ansi-clip detail.ansi
# s, drag, T: save raw ANSI for terminals (NOT Discord)

twhy photograph.jpg --output-png-clip share.png
# s, drag, i: copy a real PNG for Discord and save share.png
# s, drag, I: save share.png without using the clipboard

# In SSH, tmux, or any environment without an image clipboard helper:
twhy photograph.jpg --clipboard off --output-png-clip share.png
# s, drag, I: save PNG, then upload it to Discord

twhy document.pdf --clip-source screen     # plain Copy uses screen glyphs
```

No clip file is created at startup, on drag release, or merely when quitting.
A flag-supplied destination, or a path entered through Save, becomes the session's
**latest-clip destination** for that format. Subsequent Copy/Save actions replace
it; use **`--no-overwrite`** to refuse replacement. A single clip can contain many
areas. To keep several independent export files, use separate destinations or
move a saved clip aside.
Text/ANSI files are UTF-8 with LF line endings and a final newline;
rectangular spaces are not trimmed. PNG files are binary image data. Suggested
filenames are `selection.txt`, `selection.ansi`, `selection.png`, and
`regions.geojson`; no suggested filename is derived from the input.
Publication is atomic. The input image, its hard-link aliases,
output symlinks, directories and nonregular targets are rejected. Parent-directory
symlinks are allowed. Explicit text, ANSI, PNG and GeoJSON destinations must be
different files.
File failures remain visible and leave the viewer and selection usable. An
accepted file save is joined on shutdown; no late OSC bytes are sent after exit.

### GeoJSON annotation selections

Rectangle and polygon areas support the same export keys. **`a`** adds another
area; switching to the other **s/v** tool retains the existing areas, allowing
mixed-shape selections. Use **`[` / `]`** to choose an area and **`n`** to rename it.
The status stays compact: `Name: clever-copper-otter (n to rename)`.

Every area receives a fresh **UUIDv4** and a **coolname**-generated three-word
slug. Generated labels are random identifiers, **not** descriptions,
classifications or biological interpretations. Short three-component slugs are
chosen from coolname's standard vocabulary; no custom medical vocabulary is used.
Generated names do not repeat within a viewer session; UUIDs identify features
across sessions. Copying, saving, reopening a polygon or editing its geometry
keeps its ID. Renaming preserves the ID and changes `name_generated` to `false`.
A new area receives a new ID. Accepting an unchanged name keeps the existing flag.

**`j` / `J`** copies / saves one `FeatureCollection` with a feature for every
nonempty area, in creation order. Each feature contains only `type`, `id`,
`geometry`, and properties `name`, `name_generated`, `selection_type`.
**No source path, filename, source URL, page, series, Z/T indices, image dimensions, machine
identity or inherited metadata is exported.** The source path remains internal
for PDF text extraction and input-overwrite protection. Save destinations can
be preconfigured with `--output-geojson-clip regions.geojson`.

Geometry uses **source-image pixels**: top-left origin, X rightward, Y downward.
This is the image-annotation convention used by tools such as QuPath, not
geographic longitude/latitude. Import against the **same image and orientation**.
PDF geometry uses the **frozen displayed raster's pixel grid**, not PDF points or
a cross-DPI coordinate system; export a matching raster or explicitly transform
the coordinates before importing elsewhere. The viewer does not assemble areas
from different PDF pages, OME series or Z/T planes into one collection. Record
the displayed Z/T indices separately and select the same plane in the application
consuming the anonymous GeoJSON.

Polygons must enclose an area without crossings or repeated vertices. Geometry
is intersected with the source image rather than treating letterboxing as image
data. Fully outside/degenerate ROIs are rejected. If clipping a concave polygon
at the image edge splits it into disconnected parts, select those parts as
separate areas. Validation errors retain the selection and do not modify files
or the clipboard. Native QuPath import has not been exercised in this pass.

This prevents **automatic provenance leaks**, not identification from selected
pixels, PDF text, manually supplied labels, or the surrounding terminal UI.
These exports are not a redaction or deidentification feature.

### Plain ASCII and full-terminal viewing

**`m`** selects the artwork family: **detail** (Braille), **shape** (Unicode
strokes), **simple** (density), and **blocks** (two-color half-blocks). Press
**`t`** to toggle the family's remembered color preference. In monochrome,
**`m` cycles detail / shape / simple**, skipping blocks, which require color.
**`M`** separately selects strictly monochrome ASCII density ramps: **classic**,
**fine**, and **bold**. `M` never turns on color or selects Unicode glyphs.

Switching between `m` and `M` first restores that family's last-used style;
subsequent presses advance. Switching to `M` does not change the remembered
artwork color setting, so `m` returns to either colored or monochrome artwork
as you left it. Pressing `t` while in `M` updates the remembered `m` preference
but leaves the strict ASCII screen unchanged. **`b`** still temporarily previews
colored blocks and restores the exact previous style, even a monochrome Braille
or strict ASCII ramp.

The status identifies the current ASCII style, and the footer keeps the short
`m:art M:ASCII` hint visible. Both keys also work while selecting; the frozen
cached samples are redrawn, not reread. Area coordinates, names, IDs, and the
selection's overall bounding box stay unchanged. If a high-detail style is
selected from a coarser cached preview, its apparent detail is limited by those
existing samples. Text and ANSI exports in an ASCII preview contain only
ordinary ASCII characters with space-padded gaps, and no color escapes. Press
`m` to return to the remembered artwork mode and color. Leaving selection
does not change the normal viewer's rendering mode.

**`f`** toggles true full-terminal image viewing. **f** or **Escape** restores the
controls, with no permanent corner hint or reserved row. Selection and its copy
keys still work there. Name and save entry temporarily overlay the bottom row;
they do not shrink the image or discard selections. Escape cancels entry first,
then selection, then full-terminal mode, one level at a time.

### Clipboard transport and remote terminals

**`--clipboard auto`** (the default) first tries an available local clipboard
helper when not in SSH/tmux/Screen: `pbcopy` on macOS, `clip.exe` on Windows, or
`wl-copy`/`xclip`/`xsel` for a detected Wayland/X11 session. These optional commands
are invoked without a shell, with a two-second timeout; no package dependency
is added and no image converter is invoked. Over SSH or inside a multiplexer,
or when helpers are absent/fail, auto sends a write-only **OSC 52** request through
the viewer's terminal output. `--clipboard osc52` selects that route explicitly.
`--clipboard off` disables clipboard delivery; Copy then uses the configured
file or offers the Save prompt. Save never accesses the clipboard.

OSC 52 targets the terminal's clipboard, which can be on your local computer even
when twhy runs remotely. Terminal support, permissions, multiplexer forwarding
and size limits vary. The UI therefore says **"Sent OSC 52"**, not "clipboard
confirmed". twhy never queries/reads the clipboard, probes its contents, bypasses
terminal policy, or changes your terminal/tmux settings. Its OSC payload limit
is **64 KiB of UTF-8 text**, with an explicit error rather than truncation. Some
terminals impose smaller limits. File export has no OSC limit and is the reliable
fallback. When a configured file saves but clipboard delivery fails, the status
reports both outcomes; the successful file is kept.

For iTerm2, the relevant preference is **General > Selection > Applications in
terminal may access clipboard**. For normal tmux sessions, application-originated
OSC 52 needs `set -s set-clipboard on`, a working `Ms`/clipboard capability for the
outer terminal, and the outer terminal's permission. This also allows other
applications in that tmux server to set the clipboard, so enable it only in a
trusted environment. Nested multiplexers and tmux control-mode integrations may
need their own configuration. twhy sends ordinary OSC 52, not DCS passthrough.

References: [XTerm OSC 52](https://invisible-island.net/xterm/ctlseqs/ctlseqs.html),
[tmux clipboard](https://github.com/tmux/tmux/wiki/Clipboard),
[iTerm2 selection preferences](https://iterm2.com/documentation-preferences-general.html),
[PDFium text API](https://pypdfium2.readthedocs.io/en/stable/python_api.html).

### RAM-only overviews

An ordinary image's decoded base pixels are retained at full resolution. NumPy
builds 2x, 4x, 8x, ... area-mean levels through 1x1, with explicit scale factors.
Partial odd-sized edges use only their real pixel support. Sums/counts are carried
before rounding, so successive levels do not amplify rounding or overweight a
partial edge. Integer overview samples are rounded back to their source dtype.
Zooming in returns to the original decoded base, not an enlarged thumbnail.

For typical two-dimensional images the retained pyramid is approximately **4/3
of the base raster bytes**; very skinny images can approach twice the base.
Decoding, copies, float64 sum/count scratch, and display previews add to peak RAM.
Neither `--cache-mib` nor `--max-read-pixels` caps this initial decode/build or the
retained pyramid. PDF pages can additionally have old/new pyramids briefly alive
during a handoff, plus worker scratch and pipe-transfer copies. `--pdf-cache-pages`
bounds retained page count, not peak process-tree RSS. High DPI on a large PDF
page can require substantial RAM; lower `--pdf-max-dpi` for a smaller footprint.
The existing preview-cache and per-read limits still govern interactive sampling. Pillow's large-image safeguards remain enabled; they are not globally
disabled. PDF native dimension limits and allocation errors remain errors rather
than silently reducing the requested DPI. No intermediate image, pyramid file,
or disk cache is written. Only an explicitly requested snapshot or clip export creates output.

## Viewer

```bash
twhy slide.ome.tif                       # auto: color half-blocks or simple fallback
twhy slide.ome.tif --mode blocks         # force half-blocks
twhy slide.ome.tif --mode shape          # curves, strokes, quieter shading
twhy slide.ome.tif --mode detail         # spatial Braille
twhy slide.ome.tif --mode simple         # unchanged legacy ASCII

# Channel indices are zero-based. Repeating the option selects a composite.
twhy multiplex.ome.tif --channel 0 --channel 2

# Raw intensity limits, not percentiles. These initialize all selected channels.
twhy multiplex.ome.tif --channel 0 --lower 250 --upper 12000

# RGB remains one logical channel containing its three color samples.
twhy brightfield.ome.tif --mode blocks
twhy slide.svs --mode blocks              # Aperio whole-slide RGB, regional reads

# Select one OME image series, or start at a particular base-pixel field of view.
twhy slide.ome.tif --series 1
twhy slide.ome.tif --region 10000 12000 2500 1800
```

The image occupies the main pane. The sidebar shows channel selection and the
focused channel's lower limit, upper limit, gamma, and pseudocolor. It can be hidden with `c`,
and automatically hides below 70 terminal columns. The terminal's own pane can
still be split by tmux; twhy does not implement a shell or manage tmux sessions.

| Control | Action |
|---|---|
| Mouse wheel over the image; `+` / `-` | Zoom, anchored to the pointer for the wheel |
| Arrow keys; left-button drag | Pan the image |
| `r` or Home | Fit the whole image; cached overview when ready, sampled preview while preparing |
| `d`; click Z / T / Series | Choose the dimension navigated by brackets/PageUp/PageDown |
| PageDown / `]`; PageUp / `[` | Next / previous item on the active dimension |
| `p`, number, Enter | Jump to active Z/T/series index (0-based); PDF pages stay 1-based |
| `s`; selection toolbar | Select/copy a rectangle; see the selection controls above. |
| `c`; Tab | Toggle the sidebar; move focus between image and channels |
| `,` / `.`; sidebar wheel | Focus the previous / next channel; scroll through the full list |
| PageUp / PageDown with sidebar focus | Move one visible page through the channel list, not PDF pages/OME series |
| Home / End with sidebar focus | Focus the first / last channel |
| Enter with sidebar focus | Solo the focused channel, including channels above index 8 |
| `m` / `M`; `f` | Cycle artwork (color or mono) / strict ASCII ramps; toggle full-terminal view |
| Space; click a sidebar channel | Toggle the focused channel in the composite |
| `1` through `9` | Solo channels 0 through 8 |
| `l` / `u` / `g` | Enter the focused channel's lower / upper limit / gamma |
| `h`; click a color swatch | Edit the focused intensity channel's color (hex/name/default); swatch clicks focus without toggling the channel |
| Enter; Escape or Ctrl-C while editing | Apply; cancel numeric/color entry |
| `a` | Estimate and lock contrast from the focused channel's visible preview |
| `H` | Toggle the focused channel's text histogram; drag `^L`/`^U` or use `l/u` |
| `A` | Estimate/apply a fixed dataset-wide (or single-Image) range for the focused channel |
| `L` in histogram view | Toggle log/linear counts; raw intensities remain linear |
| `m` | Enter/cycle detail / shape / simple; include blocks only when color is on |
| `b` | Temporarily preview colored blocks; restore the previous style/color, including strict ASCII |
| `t`; `i` | Toggle the `m` family's remembered color (while `M` stays ASCII); reverse ink density |
| `?`; `q` or Ctrl-Q | Toggle key help; quit |

When the sidebar has keyboard focus, Up/Down selects its focused channel. At least
one channel must remain selected. The number shortcuts do not change the zero-based
indices shown in metadata or accepted by `--channel`. **Tab** puts keyboard focus
in the sidebar. Its header shows the visible zero-based index range and total
channel count; the focused row stays visible as it scrolls. On the canvas,
PageUp/PageDown retain their document meaning. **`[` / `]`** remain document
navigation while browsing, regardless of sidebar focus. Compact sidebar controls
leave more rows for channels, including in short terminals.

### Rendering modes

| Mode | Rendering behavior | Plain text / monochrome |
|---|---|---|
| `auto` (CLI default) | Half-blocks on Unicode-capable terminals with 256 or truecolor support; otherwise simple. | Plain snapshots: simple; `--ansi` snapshots: blocks. |
| `detail` | Eight-dot Braille with local sharpening, tone-balanced dot counts, and spatial dot placement. | Yes, UTF-8 Unicode. |
| `shape` | Canonical stroke matching with curves, diagonals, punctuation, letters, and subdued tonal fills. | Yes, UTF-8 Unicode. |
| `simple` | Original ` .:-=+*#%@` brightness ramp and original colored-ASCII semantics. | Yes, ASCII. |
| `blocks` | Original upper/lower RGB half-block display. | Requires color; snapshots require `--ansi`. |

`--mode auto` is resolved by the CLI before constructing `TextRenderer`. For
interactive viewing it honors `NO_COLOR`, `PROMPT_TOOLKIT_COLOR_DEPTH`, and
`COLORTERM` (using prompt_toolkit's own default color depth otherwise). It chooses
blocks only with a TTY, an encoding that supports `▀`, and at least 256 colors.
256-color terminals approximate the two RGB colors; truecolor terminals reproduce
them more faithfully. TERM=dumb/unknown, limited color depth, or an unsupported
encoding selects `simple`. The terminal cannot reliably report installed glyphs;
if your font lacks `▀`, explicitly choose `--mode simple`. No active terminal
probes are sent. Explicit `--mode blocks` overrides the heuristic. In interactive viewing,
`NO_COLOR=1` or a reported one-bit terminal also initializes the actual renderer
in monochrome, rather than merely hiding terminal color escapes. Consequently,
pressing `m` cycles only detail/shape/simple until `t` enables artwork color.
Explicit `--no-color` has the same monochrome cycling behavior. A terminal that
cannot emit colors will still suppress color even if the user presses `t`.

In snapshots, plain `--snapshot` with auto produces **simple** text, while
`--snapshot --ansi` with auto produces truecolor blocks. Explicit `--no-color`
with auto chooses simple in both paths. Explicit modes remain unchanged.

`--mode ascii` remains an alias for `simple`, including in `TextRenderer`.
The canonical `renderer.mode` value for that alias is `"simple"`. Custom Python
`ramp=` values belong to `simple`; the structured modes have their own vocabulary.
The library's `TextRenderer()` default stays `detail` because it has no terminal
context and should not depend on environment variables.

Detail and shape both retain **8 rows by 4 columns of display samples per terminal
cell**, instead of collapsing its shape into one average intensity. Detail groups
those samples into eight addressed Braille dots, rounds the local ink count with a
fixed ordered pattern, and puts those dots at the strongest sample positions.
Shape uses a relief-style transform to emphasize ridges and texture, then balances
tone with normalized stroke correspondence. Nearly flat areas use a quiet density
ramp instead of arbitrary letters. These are deterministic display algorithms,
not learned models, segmentation, or quantitative image measurements.

**Neither new mode paints image-dependent cell backgrounds.** Geometry and tone
remain in the characters themselves when colors are stripped. Optional color adds
one foreground hue per character; it cannot give eight Braille dots eight different
colors. The interactive canvas retains its shared dark background.

The shape vocabulary uses hand-authored geometric descriptors, not measured font
rasters. Unicode appearance and spacing depend on the terminal's fonts; no font
files are bundled, discovered, or downloaded. Use `simple` for a strict ASCII
fallback. Detail is a high-detail attempt within these text constraints, not a
claim of an optimal reconstruction. Ordered patterns are screen-grid anchored;
there is no motion registration or guarantee against shimmer during panning.

Richer sampling can choose a finer stored pyramid level and take longer to render.
The existing source-read budget still applies. If a large or poorly pyramidal
input cannot supply a complete native overview within that budget, interactive
opening uses a labelled sampled overview, not a center crop. Zooming into an
affordable region returns to native regional sampling. Optional idle-time overview
preparation scans the coarsest native level in bounded chunks, subject to a
separate total-work cap.

### Contrast and color

Windowing is `clip((value - lower) / (upper - lower), 0, 1) ** (1 / gamma)`.
Larger gamma brightens midtones. The source file and decoded source intensities
are never modified. Lower and upper must be finite, upper must exceed lower, and
gamma must be finite and positive. Invalid numeric edits stay in the editor rather
than crashing the viewer or silently accepting a different value.

Unsigned RGB starts with its dtype's full intensity range and a shared window for
all three RGB samples, preserving their relative balance. Other image channels
initially use the 1st and 99.5th percentiles of the first finite preview, with explicit
constant/sparse-field handling. These are **preview-based estimates**, not a
whole-slide stain-normalization procedure. Zeros participate. Initial windows
remain fixed as the camera moves. Pressing `a` deliberately re-estimates the focused
channel from the current visible preview; manual `l/u` values remain in raw units. Gamma is dimensionless and is preserved
when `a` re-estimates the lower and upper limits.

Multiplex composition windows each selected channel separately, adds a deterministic
pseudocolor, and clips the composite. Default colors are assigned by channel index,
not by inferred marker identity. Single-channel intensity images default to white.

**`h` edits the focused channel's hue/color**, alongside `l/u/g` for its lower
limit, upper limit and gamma. Use `,`/`.` or the sidebar to focus a channel first.
A two-cell color swatch sits at the right of each intensity channel row. Clicking
that swatch focuses the channel and opens its color editor **without toggling it**;
clicking the rest of the row still toggles visibility. The focused channel's
**h: Color** row also opens the editor when clicked.

The entry starts with the current hex color. Use **Ctrl-A, Ctrl-K** to replace it,
then **Enter** to apply; **Escape** or **Ctrl-C** cancels. Accepted input:

* `#3366FF` or `3366FF`; short hex `#36F` or `36F` also works.
* `blue`, `cyan`, `magenta`, `red`, `green`, `yellow`, `orange`, `purple`/`violet`,
  `white`, `black`, or `gray`/`grey`, case-insensitive. These are an explicit small
  palette: RGB primaries use full intensity, orange is `#FF8000`, purple/violet is
  `#8000FF`, and gray/grey is `#808080`. Arbitrary CSS names/functions are not parsed.
* `default` restores that channel's original palette color exactly.

Invalid input stays in the editor and leaves the prior color intact. Editing a
hidden channel does not select it or read its pixels. Colors are independent of
contrast/gamma, remain fixed while panning, zooming and toggling channels/modes,
and are available with the sidebar hidden or in full-terminal mode. Changing a
visible channel's color rerenders the current samples on the existing worker,
without rereading image data, even when `--cache-mib 0` disables the preview LRU.
If a camera/channel/resolution change is pending, its new view can require its
normal read. Background overview preparation remains separate work.

These are **intensity-channel pseudocolors**, not a color-balance control for
native RGB images, photographs, or PDFs. RGB keeps its original three samples;
`h` explains that distinction instead of tinting the picture. Color entry does
not switch a monochrome/ASCII view into color. Press `t` to enable artwork
color, then `m` to return from a strict `M` ramp. Color remains independent
of glyph selection.
Controls remain frozen while selecting; subsequent ANSI and PNG clips use the
chosen displayed colors, including when cycling selection preview styles.

Colors are session-local, not written into the input or a settings file. Opening
a different TIFF/Zarr series resets its colors and contrast to that series' defaults;
there is no cross-series marker-name matching or persistent palette in this pass.

### Stack-wide estimates and text histograms

Interactive scalar Z/T stacks automatically perform one fixed-budget estimate
per selected channel, on the existing display worker between foreground reads.
The initial preview limits are provisional; a completed estimate is applied
once, not per section. Any manual limit/gamma edit or visible-preview `a`
protects that channel from queued and in-flight automatic applications. Explicit
CLI `--lower`/`--upper` limits are never automatically replaced.
`--no-stack-contrast` disables automatic estimation, but H/A remain available.
Ordinary 2D opening and snapshot contrast retain the preview policy. Snapshots
share the new middle-Z/T=0 default but do not launch a dataset contrast scan.

H replaces only the plot area, not the selected source or image camera. The
histogram follows channel focus. Clicking a channel label in this mode changes
focus without toggling visibility; color swatches retain their hue editor.
The histogram estimates the fraction of finite base pixels, including real zeros.
The X axis is raw intensity; L toggles only the Y count scaling. Carets ^L/^U
are the same display limits edited by l/u. Dragging them never rereads pixels.
Intervals refer to the estimator's recommendation, not a manually dragged limit.
A deliberately applies the cached recommendation or computes it if absent.

Histogram results retain bounded sample arrays under a 32 MiB payload LRU.
Eviction does not alter locked windows. Image selections/GeoJSON export are
unavailable in histogram mode, so plot coordinates cannot be mistaken for image
coordinates. H restores the camera and image view. Fullscreen and monochrome
character modes remain available. Small terminals show an enlargement message.

The [contrast methods guide](contrast-estimation.md) defines the reusable
`ContrastConfig`, `ContrastEstimator`, `ContrastEstimate`, `estimate_contrast`
and `render_histogram` interfaces, defaults, sampling equations, confidence
limitations, RGB handling, and publication-oriented evaluation plan. The default
upper-limit policy preserves observed excess intensity mass; this is a display
heuristic, not an assertion of biological positivity or freedom from hot pixels.

### Set channel colors at startup or in a snapshot

Repeat **`--channel-color INDEX COLOR`** using zero-based **source** indices,
independently of `--channel` selection order. Colors may be set for initially
hidden channels. Duplicate overrides, invalid colors, out-of-range indices and
RGB/PDF overrides fail explicitly. Quote colors beginning with `#` in a shell.

```bash
# Deeper blue DAPI, cyan marker; works with local and remote OME-TIFF/OME-Zarr.
twhy tonsil.ome.zarr --channel 0 --channel 2 \
  --channel-color 0 '#3366FF' --channel-color 2 cyan

# The same palette for a portable ANSI snapshot.
twhy tonsil.ome.zarr --channel 0 --channel 2 \
  --channel-color 0 '#3366FF' --channel-color 2 cyan \
  --snapshot --ansi -o tonsil.ansi
```

Startup overrides apply to the initially selected series. Python frontends accept
`Viewer(session, channel_colors={0: "#3366FF", 2: "cyan"})` and the same
`channel_colors=` argument to `view_file()`. The lower-level `ChannelStyle` API
continues to accept explicit normalized RGB tuples without string parsing.

### Rendering color

Simple uses ` .:-=+*#%@`, with character density for brightness and peak-normalized
foreground color for hue. Detail/shape compute ink structure from the strongest
windowed signal and use an ink-weighted foreground hue. RGB defaults to reversed
ink density so white background becomes empty space. `i` changes that behavior.
Half-block mode uses actual windowed RGB as upper/lower half-cell colors;
inversion has no effect on half-block colors. `--no-color` uses the strongest
selected signal for a monochrome text view in the selected text mode.

Truecolor is enabled when `COLORTERM` is `truecolor` or `24bit`. An explicit
`PROMPT_TOOLKIT_COLOR_DEPTH` takes precedence; `NO_COLOR` disables it. Otherwise
prompt_toolkit selects its terminal fallback, usually 256 colors. `--ansi` snapshots always encode 24-bit SGR.
Some terminals or SSH/tmux configurations need their mouse/color forwarding enabled.
For tmux, enable its mouse handling with `set -g mouse on`; key controls remain
available when wheel or drag events are intercepted elsewhere. tmux itself is not
a runtime dependency, and automated tests do not imply every terminal is validated.

## Text snapshots and Python use

The noninteractive path uses the same planning, sampling, composition, and rendering
operations as the viewer. It never enters the alternate screen.

```bash
twhy slide.ome.tif --snapshot --columns 120 --rows 40  # auto: plain simple text

twhy slide.ome.tif --snapshot --ansi -o preview.ansi      # auto: truecolor blocks

twhy slide.ome.tif --snapshot --mode shape --no-color -o shape.txt

# Strict ASCII, preserving the original snapshot rendering:
twhy slide.ome.tif --snapshot --mode simple -o preview.txt

twhy slide.ome.tif --snapshot --mode blocks --ansi -o preview.ansi

# Full-slide snapshots also work when no native coarse level fits the read budget.
twhy slide.svs --snapshot --ansi --max-read-pixels 100000 -o whole-slide.ansi
```

Plain snapshots contain no escape sequences. `--color` and half-block snapshots
require explicit `--ansi`. Existing output files are replaced by default; use
`--no-overwrite` to refuse replacement before reading pixels. File output is
published only after the entire text frame is ready. The input image cannot be
used as an output, including through a symlink or hard link. No snapshot is written
implicitly when the viewer exits.

### Render an array without opening a file or terminal

```python
import numpy as np
from twhy import IntensityWindow, TextRenderer

pixels = np.arange(4096, dtype=np.uint16).reshape(64, 64)
normalized = IntensityWindow(lower=100, upper=3500, gamma=1.2).apply(pixels)
frame = TextRenderer(color=False).render(normalized, columns=64)
print(frame.to_text())
```

Input arrays are YX grayscale or YXS RGB. `TextRenderer` takes normalized values
in `[0, 1]`; raw intensity conversion is an explicit separate operation. Omitted
`rows` preserves square source-pixel shape using the configured terminal-cell
height/width ratio, which defaults to 2.0. Explicit rows selects the output geometry.
Nonfinite samples remain missing, not fabricated zero-intensity image data.

When sampling a source yourself, always obtain the required raster dimensions
from `renderer.sample_shape(columns=..., rows=...)`. Do not assume that terminal
rows/columns are the sample-grid dimensions. Detail/shape return `(rows * 8,
columns * 4)`; simple returns `(rows, columns)` and blocks `(rows * 2, columns)`.
Structured sample grids are capped at 4,194,304 positions before resampling;
this is a separate bound from `ViewSession`'s source-read budget.

A `TextImage` owns read-only `characters`, optional `foreground`, and optional
`background` arrays. `to_text(ansi=False)` returns plain text, `to_text(ansi=True)`
adds SGR colors, `crop(y0, y1, x0, x1)` owns an exact half-open cell rectangle
including colors, and `iter_runs(row)` exposes framework-independent styled runs for
other applications. No serialization includes cursor movement. `resample_image`
and `compose_channels` are independently usable public functions.

### Read and render a field of view

```python
from twhy import TextRenderer, ViewSession, open_image

with (
    open_image("multiplex.ome.tif") as image,
    ViewSession(image, name="Multiplex", cache_mib=32) as session,
):
    renderer = TextRenderer(mode="detail", color=True)
    viewport, limited = session.fit(
        columns=120, rows=40, renderer=renderer, channels=[0, 2],
    )
    sample_rows, sample_columns = renderer.sample_shape(columns=120, rows=40)
    plan = session.plan(
        viewport, columns=sample_columns, rows=sample_rows, channels=[0, 2],
    )
    samples = session.sample(plan)
    styles = session.prepare_styles(samples)
    frame = session.render(samples, styles=styles, renderer=renderer, columns=120, rows=40)
    print(frame.to_text(ansi=True))
    print(f"Bounded crop instead of whole image: {limited}")
```

`open_image("photo.png")`, `open_image("document.pdf", page=3, pdf_dpi=300)`,
and `open_image("animation.gif", frame=2)` yield the same open Omeify Image
contract. Ordinary files have only logical channel 0; use `channels=[0]` for the
example above. `open_image` closes its yielded image on context exit, after the
session has closed. As with other Omeify array images, retaining references to a
closed array-backed image retains its pixels; release those references to free
its RAM. Opening an image does not itself import the terminal UI.

A `Viewport(x, y, width, height)` uses **base-image pixel-edge coordinates**.
`pan()` and `zoom()` return new viewports. A source's `read_region()` instead uses
coordinates in the requested pyramid level. `ViewSession.plan()` uses declared
`ImageLevel.downsample_yx` when known, including odd-size edge footprints. For an
unknown reduced-level scale it retains the former extent-fit display approximation,
flagged by `plan.level.approximate`, the live status, and snapshot stderr. That
fallback is for browsing, not exact registration or a physical-calibration estimate. Physical pixel anisotropy participates in fit geometry;
unknown calibration means square pixels, not an invented microns-per-pixel value.

To change an individual sampled channel's style:

```python
from twhy import ChannelStyle, IntensityWindow

# Run inside the source context above; sampled channel order is [0, 2].
styles = [
    ChannelStyle(IntensityWindow(100, 12000), color=(0.35, 0.55, 1.0)),
    ChannelStyle(IntensityWindow(300, 24000, gamma=1.4), color=(1.0, 0.3, 0.5)),
]
frame = session.render(samples, styles=styles, renderer=renderer, columns=120, rows=40)
```

`ViewSession` borrows an already-open Omeify Image and owns its display caches.
Closing the session does not close the image. Closing/reopening the image ends the
session's usable lifetime, including cache hits. Independent `ViewSamples` and
`TextImage` values remain inspectable afterward.
For embedding a frontend, `from twhy.viewer import Viewer` provides
`await Viewer(session).run()`; the caller retains the source context while it runs.
This borrowed single-image workflow does not turn an immutable Image into a
changing PDF document. For file navigation and progressive PDF refinement, use:

```python
import asyncio
from twhy.viewer import view_file

if __name__ == "__main__":  # Required for spawned PDF workers in executable scripts.
    asyncio.run(view_file("document.pdf", page=3, pdf_max_dpi=600))
```

`view_file` owns its changing images/sessions and shuts down all its workers. Its
mode is an explicit TextRenderer mode (`blocks` by default); CLI `auto` selection
still belongs to the CLI. Importing the array renderer does not start workers.

## Image-backed Python use (0.2)

The former twhy `OmeTiffSource` class is removed. Omeify owns the Image/source
contract and TIFF interpretation; `open_image()` is a small file-ingress helper
that also decodes ordinary inputs into Omeify array images. `ViewSession(image)`
owns bounded display. There is one sampling/rendering path, not a file path and
a separate simulator path. `max_read_pixels=` belongs to the session. The CLI
retains its original options and controls.

```python
# With an already rendered Mocktome mIF product:
from twhy import TextRenderer, ViewSession

with mif.as_image() as image, ViewSession(image, name="Mocktome") as session:
    renderer = TextRenderer(color=False)
    view, limited = session.fit(columns=100, rows=35, renderer=renderer)
    rows, columns = renderer.sample_shape(columns=100, rows=35)
    samples = session.sample(session.plan(view, rows=rows, columns=columns))
    frame = session.render(samples, styles=session.prepare_styles(samples),
                           renderer=renderer, columns=100, rows=35)
    print(frame.to_text())
```

Mocktome 0.5 supplies `as_image()` for its existing eager outputs. It is not a
new random exposure per read. Other providers can implement Omeify ImageSource
without a dependency on Mocktome or twhy. There is no TIFF serialization in this
Python workflow. Sources with one level still obey the same read budget; the
session does not fabricate a cheap whole-image overview.

A session may be used explicitly with `close()` rather than `with`, but it cannot
be reopened. On a real terminal, `await Viewer(session).run()` borrows the session;
it waits for its worker before returning. Notebook text snapshots use `print()`;
this release does not add a graphical notebook widget.

## Bounded reads and caching

The regional source boundary remains Omeify. twhy never reads TIFF pages through
a second decoder, parses competing OME metadata, or runs Omeify's conversion or
mutation commands. The session selects from the source's supplied levels, whether
stored TIFF levels or the explicit RAM pyramid created for an ordinary input.
Only a clipped, intersecting source region is requested. TIFF tiles are decoded
by Omeify; an ordinary array-backed source returns a region of its RAM raster. Separable area averaging reduces the bounded rectangle to the
terminal sampling grid, including fractional camera positions and letterboxing.
Raw preview means use float64 so narrow windows on uint32 data survive resampling.

There are three deliberately different caches:

* The provider-owned source cache, retained across channel, XY-level and Z/T
  changes. Omeify owns its aggregate budget and eviction; twhy does not flush it
  on ordinary navigation or create a second raw tile cache. One persistent dataset
  is retained for the displayed series. Old/new series may overlap during a safe
  handoff. Omeify speculative prefetch is not enabled by this frontend.
* twhy's byte-bounded LRU of **raw resampled previews**, 32 MiB by default. Contrast,
  gamma, coloring, and density can reuse these samples without reading TIFF data.
  Richer previews take more bytes, so the same cache holds fewer of them. Detail
  and shape share a sample-grid geometry and can reuse one another's raw previews.
  The current rendered frame and its style runs are retained for cheap terminal repaint.
* A separate **64 MiB runtime overview cache**, counting completed arrays and one
  in-progress build together. It retains unwindowed full-coverage box reductions
  per selected channel, evicts least-recently-used entries, and never writes files.

One background display worker performs sampling and rendering. New camera requests replace
pending older ones; an in-flight decode completes safely but its stale result is
not displayed. Quitting joins the worker before returning control to the source's
context manager. Decode errors exit with their cause rather than leaving a stale
frame presented as a successful new view. File navigation has a separate, single
source-loader thread. PDF refinement has at most two native worker processes;
private-pipe reception runs off the UI thread. Sources are never closed or replaced
under an in-flight display read.

`--max-read-pixels` defaults to 4,194,304 source samples **per foreground request**,
counting selected channels and RGB samples. Strict library plans reject larger
reads, and the explicit library `ViewSession.fit()` retains its strict bounded-crop
contract. The **interactive viewer instead always opens with a whole-image camera**:
using native pixels, a completed runtime overview, or the labelled sampled
preview as necessary. Overview construction is separately budgeted extra I/O,
not a loophole that claims a full native scan fits in one foreground request.

### Whole-slide zoom-out and cached overviews

The initial interactive camera now **always fits the entire image**, as snapshots
already do. Native pyramid reads take priority when affordable. Otherwise twhy
attempts a full-coverage cached reduction for up to **two seconds** before the
first image frame, without blocking the terminal event loop. **No sparse image is
painted while that attempt is running.** If the reduction completes, the first
image frame is the cached full-coverage overview. If it does not, the first frame
uses the labelled bounded sampled overview rather than a center crop; the idle-time
builder may improve that same camera later. Wheel/`-`
zooms out farther, and **`r`/Home** restores the whole-image fit. Blank margins
preserve the image aspect ratio. User-specified `--region` is never replaced.

After the first displayed frame, idle worker iterations may prepare a reusable
**full-coverage overview from the coarsest native level**. Every native pixel in
that level contributes to the appropriate box, including partial odd-size edges;
nonfinite values contribute no weight. Float64 weighted values and finite support
are retained before windowing, so channel contrast, gamma, pseudocolor and
rendering-mode changes do not require rebuilding the overview. No full native
level is materialized. Source metadata, physical calibration and GeoJSON's base
pixel coordinate system are unchanged; unknown native geometry stays `extent-fit`.

The worker reads one disjoint regional chunk at a time. Each chunk requests at
most **262,144 source samples**, and never more than `--max-read-pixels`, including
RGB components. Whole-image preparation necessarily reads more than one ordinary
frame's budget over time. Its separate **`--overview-max-source-pixels`** limit is
**134,217,728 samples** across the selected channel set by default. Exceeding it
skips the automatic scan, which avoids accidentally traversing a gigantic
single-level slide just because a terminal was opened.

**`--overview-cache-mib` defaults to 64**, separate from `--cache-mib` (32 MiB of
small camera previews). Completed entries plus the one unfinished build share
that cap. The reduction uses a power-of-two factor until each channel fits its
share of the cache and at most 262,144 spatial pixels. It does not allocate the
entire allowance up front. Weighted values plus support require 16 bytes per
scalar output sample, or 48 per RGB pixel. Selected channels are protected from
LRU eviction while their set is being prepared; other channel entries may be
reused or evicted. Cache contents are session-local and released on source/series
replacement or viewer shutdown. Nothing persists on disk.

```bash
twhy slide.svs                               # automatic idle-time cache preparation
twhy slide.svs --overview-cache-mib 128       # larger retention allowance
twhy slide.svs --overview-cache-mib 0         # disable preparation; retain sampled fallback
twhy slide.svs --overview-max-source-pixels 268435456  # explicitly allow more scan I/O
twhy slide.svs --startup-overview-seconds 0     # skip quick startup scan (idle build remains)
twhy slide.svs --startup-overview-seconds 3     # give a full-coverage overview longer to finish before first image frame
```

The quick-start attempt is limited by the same `--overview-max-source-pixels` and
`--overview-cache-mib` caps as idle preparation. It has **no additional hard-coded
coarse-level size threshold**: increasing `--startup-overview-seconds` can help a
larger eligible slide finish before its first frame. A single native codec read
can still overrun the deadline. Setting the time to `0` displays the sampled
fallback immediately when a native full view is unaffordable.

Foreground frames take priority over further overview chunks. Preparation uses
**the existing single display worker**, not concurrent calls into the same TIFF
reader. Zooming/panning preempts it between chunks; idle time can resume useful
work even after zooming in. Changing selected channels abandons an obsolete
partial channel build when the worker next runs; changing series drops its
session cache. Selection pauses preparation and freezes the displayed frame.
A chunk already in flight may finish, but cannot replace a selection's artwork.
Quitting joins the current read without starting another chunk. This is
cooperative cancellation, not interruption of a running native codec.

The status distinguishes **`building overview`**, **`cached overview`** and
**`sampled overview`**. Until all selected channels have a complete cache entry,
the prior <=256-patch sampled view remains available for immediate navigation.
Completion automatically redraws an overview without moving the camera or
resetting contrast. The sparse fallback also remains when preparation is disabled,
scan-capped, or fails; a failure is reported and not retried on every repaint.
When even a lower-detail native rectangle fits the read budget, twhy now uses
that complete native region before considering a sampled view. Zooming back into
an affordable detailed native region always returns to native sampling.

A cached overview is a full-coverage **display reduction of that native level**,
not recovered full-resolution detail or a quantitative measurement product.
Arbitrary subsequent camera footprints approximate within its reduced pixels,
as with a normal display pyramid. It cannot restore features already absent from
the scanner's coarsest level. It does, however, avoid the sparse fallback's gaps
between observations. Cached pixels must not be interpreted as new calibration.

Library `ViewSession.plan()` remains strict by default. To explicitly prepare an
overview, call `session.step_overview(channels)` off the UI thread until its
`pending` result is false; `published` reports completion of a channel. Each
call does at most one chunk of extra work. `cancel_overview()` drops an incomplete
build, while `clear_cache()` also removes completed overviews and camera previews.
`overview_cache_bytes` includes both finished and unfinished overview arrays.
`sample()` may use a completed cache for an explicitly allowed sampled plan,
reporting `ViewSamples.cached_overview=True`; the plan is unchanged and its
`source_samples` remains the fallback's planned budget, not a count of actual
cache-hit I/O. Snapshots now **fit the entire slide by default**, using a native level when
it is affordable, the same short full-coverage cache preparation when eligible,
or the labelled sampled overview otherwise. They do not silently export a center
crop because of a small read budget. `--region` still requests an exact native
field and retains its strict read-budget check. Snapshot diagnostics distinguish
`Cached full-coverage overview` from `Sampled overview` on stderr. These are
visualization products, not quantitative measurements. The time limit is checked
between reads; a single slow native codec read may overrun the nominal deadline.
Time-limited snapshot output can therefore differ with I/O performance; for a
repeatable sampled fallback set `--startup-overview-seconds 0` (and for an exact
field use `--region`).

These sample-count and array-cache budgets are **not a process-RSS cap**.
Decoder buffers, masks, area-averaging intermediates, metadata, and terminal output
also use memory. Omeify's source-session retained-payload budget defaults to 64 MiB;
oversized native blocks can bypass retention and still require large decode
allocations. A poorly tiled source can still be slow.

## Current scope

The CLI supports the OME-Zarr and ordinary image/PDF formats listed above, plus **Aperio
SVS** (RGB `.svs` files through Omeify's Aperio reader) and tiled or
striped **OME-TIFF**, including stored SubIFD pyramids, grayscale, RGB, and planar
multi-marker images. Python sessions accept an open Omeify intensity or RGB Image,
including array and procedural backends. PDF pages and TIFF series can be navigated
in-app; `--page` and `--series` choose the initial selection. OME-TIFF and
OME-Zarr support Z-only, T-only and combined Z/T navigation; `--z-index` and
`--t-index` choose the initial plane. Raster `--frame` selection remains startup-only.
Coarse-volume XYZ previews, time playback, projections, multi-file TIFF, label-specific
categorical coloring, raw vendor formats, persistent annotation editing, segmentation overlays, saved view settings and ICC-managed color are not implemented. Explicit categorical LabelImages are rejected rather than assigning continuous
brightness to arbitrary object IDs. OME-TIFF alone does not declare label semantics;
CLI users must not interpret numeric label brightness as expression. The reader fails clearly
on unsupported inputs. Font-dependent density and terminal color approximation
remain limitations of text rendering.

## Demo and tests

```bash
python examples/make_demo.py --output-directory /tmp/twhy-demo

twhy /tmp/twhy-demo/synthetic-rgb.ome.tif
twhy /tmp/twhy-demo/synthetic-mif.ome.tif --channel 0 --channel 2

python -m pip install -e '.[dev]'           # includes PDF integration tests
python -m pytest --cov=twhy --cov-report=term-missing
ruff check .
python -m build
```

The demo creates deterministic tissue-like rings, nuclei, and marker signals. It
contains no patient data and is not a biological simulation. Tests independently
write real TIFFs with tifffile, read them through the real Omeify dependency, compare
resampling with a small rectangle-intersection oracle, and exercise the actual
prompt_toolkit application with keyboard and SGR mouse events. POSIX PTY tests also
check alternate-screen, mouse, and cursor restoration. Some codec/terminal/platform
combinations require separate validation; see [the validation record](docs/validation.md) for
what was actually run for this patch.

## License

Apache-2.0. The original repository license is unchanged.
