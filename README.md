# twhy

**Whole-slide microscopy, ordinary images, and scientific PDFs, right in your terminal.**

`twhy` is a zoomable, full-screen image viewer made of *actual terminal characters*. Open an OME-TIFF, SVS, or OME-Zarr slide, explore multichannel fluorescence and Z/T stacks, inspect a PNG, or page through a PDF. No browser, image server, X11, graphics protocol, or GPU required.

I had a use case for this on a remote cluster with thousands of images. Sometimes
I just needed the tissue's shape, a rough count of regions of interest, or to tell
a big chunk of tissue from a few tiny core needle biopsies. An ASCII-art
representation of a preview from the image pyramid seemed like it would do the job.

Then working in tmux, switching the active area of the terminal with either the
mouse or keyboard, got me wondering... just how far can we push a text-based image
viewer? And thus began `twhy`. I've been having a little fun with AI slop along
the way, and now it opens PDFs and lets me draw polygons on pathology images.
It's ridiculous, but I'm actually going to use it.

<p align="center">
  <a href="https://github.com/jason-weirather/twhy/blob/main/docs/media/pathology.gif"><img src="https://raw.githubusercontent.com/jason-weirather/twhy/main/docs/media/pathology.gif" width="900" alt="Real recording of twhy zooming through multiplex immunofluorescence and revealing CD8 signal in cyan on blue DAPI nuclei"></a>
</p>
<p align="center"><em>Real terminal footage: 59-channel multiplex microscopy, DAPI and CD8. Channel selection and zoom, no mock interface.</em></p>

## See it in action

These are short, automatically looping recordings of `twhy` itself. Click any clip to view it at full GIF size.

<table>
<tr>
<td width="50%" valign="top">
<strong>Whole-slide H&amp;E SVS</strong><br>
<a href="https://github.com/jason-weirather/twhy/blob/main/docs/media/he.gif"><img src="https://raw.githubusercontent.com/jason-weirather/twhy/main/docs/media/he.gif" width="440" alt="twhy zooming from an SVS whole-slide tissue overview to individual nuclei in a real H&E image"></a><br>
<small>Zoom from whole-slide tissue context into individual nuclei.</small>
</td>
<td width="50%" valign="top">
<strong>An ordinary PNG. Featuring a cat.</strong><br>
<a href="https://github.com/jason-weirather/twhy/blob/main/docs/media/cat.gif"><img src="https://raw.githubusercontent.com/jason-weirather/twhy/main/docs/media/cat.gif" width="440" alt="twhy zooming into an orange-and-white cat in a sunlit windowsill illustration"></a><br>
<small>PNG, JPEG, WebP: zoom and pan familiar images, too.</small>
</td>
</tr>
<tr>
<td width="50%" valign="top">
<strong>A scientific PDF</strong><br>
<a href="https://github.com/jason-weirather/twhy/blob/main/docs/media/pdf.gif"><img src="https://raw.githubusercontent.com/jason-weirather/twhy/main/docs/media/pdf.gif" width="440" alt="twhy switching pages in a scientific PDF and zooming into a transformer architecture diagram"></a><br>
<small>Turn pages, then zoom into figures. PDF support is standard.</small>
</td>
<td width="50%" valign="top">
<strong>Polygon selections</strong><br>
<a href="https://github.com/jason-weirather/twhy/blob/main/docs/media/selection.gif"><img src="https://raw.githubusercontent.com/jason-weirather/twhy/main/docs/media/selection.gif" width="440" alt="twhy drawing a yellow polygon selection around a tissue core and preparing it for GeoJSON export"></a><br>
<small>Select rectangles or polygons; export GeoJSON, text, ANSI art, or PNG.</small>
</td>
</tr>
</table>

## Install

Python **3.11+**. The **PyPI distribution**, terminal command, and Python import all share the name `twhy`.

Install the standalone command without changing packages in a scientific Python environment:

```bash
uv tool install twhy
# or: pipx install twhy
# or: python -m pip install twhy
```

From a cloned checkout, for development:

```bash
python -m pip install -e '.[dev]'
```

The `t_z_support` branch requires the updated **Omeify `z_t_support` checkout
at `74bf991` or a descendant with the same dataset API**, installed in the same
Python environment. Its metadata version is 0.22.2; that version alone does not
identify the branch revision. Install your local Omeify checkout before installing
this twhy branch. [Z/T setup and examples](docs/z_t_support.md).

PDF support is **included** in the standard install. No special extra or system PDF converter is needed.

## Quickstart

```bash
twhy photo.png                         # PNG, JPEG, WebP, and more
twhy paper.pdf                         # page navigation and progressive detail
twhy slide.svs                         # Aperio whole-slide RGB
twhy slide.ome.tif                     # OME-TIFF, grayscale or multichannel
twhy /data/sample.ome.zarr             # local OME-Zarr
twhy time-depth.ome.tif                # first Z/T plane; d chooses navigation axis
twhy experiment.zarr --z-index 15 --t-index 12  # explicit zero-based startup plane

# Compose two fluorescence channels with chosen colors:
twhy slide.ome.tif --channel 0 --channel 2 \
  --channel-color 0 blue --channel-color 2 cyan
```

The initial view fits the image. Wheel zoom is anchored to the pointer; pan with the mouse or arrow keys. The terminal sidebar keeps channels, colors, and contrast controls at hand.

Z/T changes preserve the camera, channels, colors and contrast. A new series still
fits and initializes its own channels. Omitted startup Z/T indices use zero for
axes present in the source; invalid explicit indices fail. Only exact-section
pyramid levels are used automatically, including when the input stores an XYZ
pyramid. [Navigation, limitations, and public test inputs](docs/z_t_support.md).


## Why a terminal viewer?

- **Whole-slide without whole-slide RAM use:** regional TIFF/SVS reads and pyramids, with bounded previews and useful zoomed-out overviews.
- **Multichannel, not just RGB:** select channels, change pseudocolors, and adjust each marker's display window and gamma without modifying source pixels.
- **PDFs and everyday images:** ordinary images use in-memory pyramids; PDFs refine progressively from a quick preview to higher-detail pages.
- **Real characters:** colored `▀` half-blocks, Braille detail, shape-oriented Unicode art, and portable ASCII modes.
- **Selection and export:** copy/save terminal text, colored ANSI, shareable PNGs, and GeoJSON polygons/rectangles.
- **Reusable Python library:** sampling, intensity normalization, composition, and rendering are available without opening the interactive terminal UI.

`twhy` works over ordinary terminal sessions, including environments where a desktop image viewer is inconvenient. It is an exploratory display, **not a color-managed diagnostic viewer** and not a substitute for measuring the original pixels.

## The keys you'll actually use

| Action | Key or gesture |
|---|---|
| Zoom; pan; fit image | Wheel or `+`/`-`; arrows or drag; `r`/Home |
| Choose navigation dimension | `d`, or click Z / T / Series in the navigation bar |
| Step/jump within that dimension | `]` / `[` or PageDown / PageUp; `p` to jump (PDF pages remain one-based) |
| Toggle a channel; focus another | Click channel/Space; `,` and `.` |
| Adjust channel color or contrast | `h` (hue); `l`/`u` (limits); `g` (gamma); `a` (auto window) |
| Switch artwork / strict ASCII | `m` / `M`; `t` toggles artwork color; `f` toggles fullscreen |
| Select region | `s` rectangle; `v` polygon |
| Export a selection | `y/Y` text, `i/I` PNG, `t/T` ANSI, `j/J` GeoJSON (copy/save) |
| Help or quit | `?` / `q` |

## From terminal annotations to full-resolution ROIs

The useful part of the joke: draw regions in `twhy`, save their coordinates as
GeoJSON, and let [Omeify](https://github.com/jason-weirather/omeify) extract them
from the original image. This example uses a calibrated OME-TIFF, series 0.
You also need the `omeify` command on your PATH; with isolated tool installs,
install it separately using `uv tool install omeify`.

```bash
# Open the source and choose where to save the annotations.
twhy slide.ome.tif --series 0 --output-geojson-clip regions.geojson
```

Zoom to the view you need, then press **`s`** for a rectangle or **`v`** for a
polygon and draw. Close a polygon with **Enter**; **`a`** adds another region in
the same view. Press **Shift+J** to save all the regions before quitting.

```bash
# Export one full-resolution image per region, with lossless compression.
omeify crop slide.ome.tif --series 0 \
  --geojson regions.geojson -o regions.ome.tif \
  --shatter by_index --compression Deflate --no-overwrite
```

This writes `regions-01.ome.tif`, `regions-02.ome.tif`, and so on, retaining all
channels from the selected series. Omit `--shatter by_index` to put the regions
into separate image series in one OME-TIFF instead.

**Full-resolution pixels, not a screenshot:** Omeify reads the original image,
not the terminal preview. Omeify writes each polygon's enclosing rectangle and
masks pixels outside the polygon by default; keep the GeoJSON for the outlines.
Use the same source image,
series, Z/T plane, and orientation in both steps. Z/T indices are not embedded
in the anonymous GeoJSON; record them and pass matching `--z-index`/`--t-index`
to Omeify when cropping a stack. Annotation placement follows the terminal
grid, so zoom in before drawing for finer boundaries.
[More crop options](https://github.com/jason-weirather/omeify/blob/main/docs/regions.md).

## Supported files

| Format | What twhy does |
|---|---|
| OME-TIFF | Regional microscopy viewing, channels, series, Z slices and time points |
| Aperio SVS | RGB whole-slide viewing using available stored levels |
| OME-Zarr | Local/HTTP(S)/optional S3, regional reads, series and Z/T navigation |
| PNG, JPEG, WebP, BMP, TGA, PPM | Ordinary raster viewing with zoom and pan |
| GIF, APNG, animated WebP | View a selected frame (not animation playback) |
| PDF | Navigate pages; progressively improve raster detail; copy embedded text from a rectangular selection |

For advanced flags, channel/series semantics, color modes, cache limits, clipboard behavior, and format caveats, use the **[full reference](https://github.com/jason-weirather/twhy/blob/main/docs/reference.md)**. Architecture notes are in [docs/architecture.md](https://github.com/jason-weirather/twhy/blob/main/docs/architecture.md).

## Try a synthetic microscopy example

The repo includes a deterministic fixture generator that creates public-safe, synthetic tissue-like RGB and multichannel OME-TIFFs. It is a renderer demonstration, not a biological simulation.

```bash
python examples/make_demo.py --output-directory /tmp/twhy-demo
twhy /tmp/twhy-demo/synthetic-mif.ome.tif --channel 0 --channel 2
```

## Python API

```python
import numpy as np
from twhy import TextRenderer

pixels = np.linspace(0, 1, 256**2).reshape(256, 256)
frame = TextRenderer(mode="detail", color=False).render(pixels, columns=80)
print(frame.to_text())
```

## Optional remote sources

Local files are the main workflow. `twhy` also supports HTTP(S) images/PDFs (bounded download) and HTTP(S) OME-Zarr (regional chunk reads). For native S3 or S3-compatible stores, install `twhy[s3]` and use your normal AWS credentials or an endpoint override. No S3 setup is needed for local images, slides, or PDFs. [Remote input reference](https://github.com/jason-weirather/twhy/blob/main/docs/reference.md#local-and-remote-inputs).

## Release media and provenance

These GIFs are edited recordings of the real `twhy` terminal viewer. Showcase sources:

- **mIF:** Tan, Y. & Kempchen, T. (2024), [*SPACEc demo dataset*](https://doi.org/10.5061/dryad.brv15dvj1), Dryad.
- **H&E whole-slide demo:** `CMU-1.svs`, [OpenSlide test data](https://openslide.cs.cmu.edu/download/openslide-testdata/Aperio/), Carnegie Mellon University, CC0 1.0.
- **PDF:** Vaswani, A. et al. (2017), [*Attention Is All You Need*](https://arxiv.org/abs/1706.03762), NeurIPS.
- **Cat:** Illustration generated with ChatGPT (OpenAI).

## License

Apache-2.0. See [LICENSE](https://github.com/jason-weirather/twhy/blob/main/LICENSE).
