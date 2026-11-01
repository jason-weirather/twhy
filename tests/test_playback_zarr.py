"""Required real OME-Zarr time-slideshow integration, not a fake dataset."""

import asyncio

from prompt_toolkit.input import create_pipe_input

from test_viewer import SizedOutput, eventually, ready
from zt_zarr_fixture import write_zarr_stack
from twhy import IntensityWindow, TextRenderer
from twhy.image_document import ImageDocument
from twhy.viewer import Viewer
from twhy.viewer.navigation import DocumentNavigation


async def test_zarr_t_slideshow_preserves_section_and_cache(tmp_path):
    path = tmp_path / "movie.zarr"
    write_zarr_stack(path, version="0.5")  # zarr is a REQUIRED dependency here.
    document = ImageDocument(path, z_index=3)
    initial = document.initialize()
    nav = DocumentNavigation(document, initial, cache_mib=0, overview_cache_mib=0)
    with create_pipe_input() as pipe:
        viewer = Viewer(nav.session, navigation=nav, renderer=TextRenderer(mode="blocks"),
                        window=IntensityWindow(0, 40000), play_fps=7)
        task = asyncio.create_task(viewer.run(input=pipe, output=SizedOutput()))
        try:
            await ready(viewer, task)
            assert not viewer.playback.playing
            assert nav.active.position == (0, 3, 0)
            cache = nav.active.dataset
            colors, windows, camera = tuple(viewer.channel_colors), tuple(viewer.windows), viewer.viewport
            pipe.send_text("P")
            await eventually(lambda: nav.active.t_index == 1 and not viewer.busy, task)
            await eventually(lambda: nav.active.t_index == 2 and not viewer.busy, task)
            await eventually(lambda: nav.active.t_index == 0 and not viewer.busy, task)
            assert nav.active.z_index == 3
            assert nav.active.dataset is cache
            assert viewer.viewport == camera and tuple(viewer.windows) == windows
            assert tuple(viewer.channel_colors) == colors
        finally:
            if not task.done():
                pipe.send_bytes(b"\x11")
            await asyncio.wait_for(task, 15)
            assert nav.active.image is None
