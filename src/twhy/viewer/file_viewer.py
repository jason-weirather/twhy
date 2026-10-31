"""File-backed frontend entry point; borrowed-image Viewer use remains unchanged."""

from __future__ import annotations

from pathlib import Path

from ..image_document import ImageDocument
from ..image_input import open_image
from ..source_input import DEFAULT_MAX_REMOTE_MIB, resolve_input, remote_scheme
from ..pdf_workers import DEFAULT_PDF_CACHE_PAGES
from ..text_renderer import TextRenderer
from ..runtime_overview import DEFAULT_OVERVIEW_CACHE_MIB, DEFAULT_OVERVIEW_MAX_SOURCE_PIXELS
from ..startup_overview import DEFAULT_STARTUP_OVERVIEW_SECONDS
from ..view_session import ViewSession
from .navigation import DocumentNavigation
from .clipping import clip_options
from .viewer import Viewer


async def _view_resolved_file(path, *, series=0, page=None, frame=None, pdf_max_dpi=None,
                    pdf_cache_pages=None, background=None, channels=(0,), window=None,
                    channel_colors=None, stack_contrast=True, contrast_config=None,
                    mode="blocks", color=True, invert=None, cell_aspect=2.0,
                    viewport=None, cache_mib=32.0, max_read_pixels=4_194_304,
                    overview_cache_mib=DEFAULT_OVERVIEW_CACHE_MIB,
                    overview_max_source_pixels=DEFAULT_OVERVIEW_MAX_SOURCE_PIXELS,
                    startup_overview_seconds=DEFAULT_STARTUP_OVERVIEW_SECONDS,
                    input=None, output=None, output_text_clip=None, output_ansi_clip=None,
                    output_png_clip=None, output_geojson_clip=None, clipboard="auto",
                    clip_source="auto", clip_overwrite=True,
                    group="", z_index=None, t_index=None, input_format="auto",
                    s3_endpoint_url=None, s3_anonymous=False,
                    source_name=None) -> None:
    """Navigate a document with its normal terminal controls and renderer.

    mode must be a resolved TextRenderer mode (the CLI resolves 'auto'). Embedded
    Python callers using PDF processes must use the normal __main__ guard in
    executable scripts. PDFium's initial quick-preview work is serialized in the
    parent; all subsequent high-detail/prefetch native work is process-isolated.
    """
    clipping = dict(source_path=path if remote_scheme(path) is None and
                    Path(path).is_file() else None,
                    output_text_clip=output_text_clip,
                    output_ansi_clip=output_ansi_clip, output_png_clip=output_png_clip,
                    output_geojson_clip=output_geojson_clip, clipboard=clipboard,
                    clip_source=clip_source, clip_overwrite=clip_overwrite)
    clip_options(**clipping)
    document = ImageDocument(path, series=series, page=page, frame=frame,
                             pdf_max_dpi=pdf_max_dpi, background=background,
                             group=group, z_index=z_index, t_index=t_index,
                             input_format=input_format, s3_endpoint_url=s3_endpoint_url,
                             s3_anonymous=s3_anonymous, source_name=source_name)
    if document.kind != "pdf" and pdf_cache_pages is not None:
        raise ValueError("--pdf-cache-pages applies only to PDF")
    if document.kind == "raster":
        name = document.source_name
        if frame is not None:
            name += f" | frame {frame} (0-based)"
        with (
            open_image(path, series=series, page=page, frame=frame, background=background,
                       s3_endpoint_url=s3_endpoint_url, s3_anonymous=s3_anonymous) as image,
            ViewSession(image, name=name, cache_mib=cache_mib,
                        max_read_pixels=max_read_pixels, overview_cache_mib=overview_cache_mib,
                        overview_max_source_pixels=overview_max_source_pixels) as session,
        ):
            renderer = TextRenderer(mode=mode, color=color,
                                    invert=session.info.is_rgb if invert is None else invert,
                                    cell_aspect=cell_aspect)
            await Viewer(session, channels=channels, channel_colors=channel_colors,
                         window=window, renderer=renderer,
                         viewport=viewport, startup_overview_seconds=startup_overview_seconds,
                         stack_contrast=stack_contrast, contrast_config=contrast_config,
                         **clipping).run(input=input, output=output)
        return
    initial = document.initialize()
    try:
        navigation = DocumentNavigation(
            document, initial,
            cache_pages=DEFAULT_PDF_CACHE_PAGES if pdf_cache_pages is None else pdf_cache_pages,
            cache_mib=cache_mib, max_read_pixels=max_read_pixels, window=window,
            auto_invert=invert is None, overview_cache_mib=overview_cache_mib,
            overview_max_source_pixels=overview_max_source_pixels,
        )
    except BaseException:
        initial.release()
        document.close()
        raise
    try:
        renderer = TextRenderer(mode=mode, color=color,
                                invert=navigation.session.info.is_rgb if invert is None else invert,
                                cell_aspect=cell_aspect)
        viewer = Viewer(navigation.session, navigation=navigation, channels=channels,
                        window=window, channel_colors=channel_colors,
                        renderer=renderer, viewport=viewport,
                        startup_overview_seconds=startup_overview_seconds,
                        stack_contrast=stack_contrast, contrast_config=contrast_config, **clipping)
        await viewer.run(input=input, output=output)
    finally:
        # Idempotent stop/close also covers invalid initial channel selection or
        # an exception before the terminal application has been constructed.
        await navigation.stop()
        navigation.close()

async def view_file(path, *, max_remote_mib=DEFAULT_MAX_REMOTE_MIB,
                    s3_endpoint_url=None, s3_anonymous=False,
                    input_format="auto", **kwargs) -> None:
    """View a local or remote document, keeping bounded downloads alive through exit.

    Unlike a per-page temp file, this one context survives PDF spawn/refinement,
    page turns and native text selection. The underlying reader remains unchanged.
    """
    with resolve_input(path, max_remote_mib=max_remote_mib,
                       s3_endpoint_url=s3_endpoint_url, s3_anonymous=s3_anonymous,
                       input_format=input_format) as source:
        label = kwargs.pop("source_name", None) or source.label
        await _view_resolved_file(
            source.path, source_name=label,
            s3_endpoint_url=s3_endpoint_url, s3_anonymous=s3_anonymous,
            input_format="zarr" if source.is_zarr else "auto", **kwargs,
        )
