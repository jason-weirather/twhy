"""Z/T navigation through real Omeify datasets and the actual terminal application."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import threading
import sys

import numpy as np
import pytest
import tifffile
from click.testing import CliRunner
from prompt_toolkit.data_structures import Point
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.mouse_events import MouseButton, MouseEvent, MouseEventType

from omeify import Image, OMETiffReader
from twhy import IntensityWindow, TextRenderer, ViewSession, Viewport, open_image
from twhy.cli import main
from twhy.image_document import ImageDocument
from twhy.viewer import Viewer
from twhy.viewer.controls import navigation_fragments
from twhy.viewer.navigation import DocumentNavigation
from test_viewer import SizedOutput, eventually, ready, send


def write_stack(path, *, axes="TCZYX", rgb=False, extra_series=False, levels=2):
    """Independent TIFF with coordinates encoded in intensities and XY levels."""
    sizes = {"T": 3, "C": 2, "Z": 5, "Y": 32, "X": 48, "S": 3}
    shape = tuple(sizes[a] for a in axes)
    coords = np.indices(shape)
    weights = {"T": 6000, "C": 2000, "Z": 200, "Y": 3, "X": 1, "S": 50}
    data = sum(coords[i] * weights[a] for i, a in enumerate(axes))
    data = (data % 256).astype(np.uint8) if rgb else data.astype(np.uint16)
    names = ["RGB"] if rgb else ["DNA", "Marker"] if "C" in axes else ["Signal"]
    metadata = {"axes": axes, "Channel": {"Name": names}, "Name": "Stack",
                "PhysicalSizeX": .5, "PhysicalSizeY": .5,
                "PhysicalSizeXUnit": "µm", "PhysicalSizeYUnit": "µm",
                "PhysicalSizeZ": 2., "TimeIncrement": 30.}
    with tifffile.TiffWriter(path, ome=True) as writer:
        for level in range(levels):
            step = 2 ** level
            selection = tuple(slice(None, None, step) if a in "YX" else slice(None)
                              for a in axes)
            writer.write(data[selection], photometric="rgb" if rgb else "minisblack",
                         metadata=metadata if not level else None, tile=(16, 16),
                         subifds=levels - 1 if not level else None,
                         subfiletype=1 if level else 0, compression="deflate",
                         resolution=(20000 / step, 20000 / step), resolutionunit="CENTIMETER")
        if extra_series:
            writer.write(np.full((16, 24), 77, np.uint16), photometric="minisblack",
                         tile=(16, 16), metadata={"axes": "YX", "Name": "Other"})
    return data


@pytest.fixture
def stack_file(tmp_path):
    path = tmp_path / "time-depth.ome.tif"
    return path, write_stack(path)


@asynccontextmanager
async def browsing_stack(path, **kwargs):
    doc = ImageDocument(path, **{k: v for k, v in kwargs.items()
                                if k in ("series", "z_index", "t_index", "input_format")})
    initial = doc.initialize()
    nav = DocumentNavigation(doc, initial, overview_cache_mib=0, cache_mib=0)
    with create_pipe_input() as pipe:
        viewer = Viewer(nav.session, navigation=nav,
                        renderer=TextRenderer(mode="blocks"),
                        window=IntensityWindow(0, 20000),
                        channels=kwargs.get("channels", (0,)),
                        channel_colors=kwargs.get("channel_colors"))
        output = SizedOutput()
        task = asyncio.create_task(viewer.run(input=pipe, output=output))
        try:
            await ready(viewer, task)
            yield nav, viewer, pipe, output, task
        finally:
            if not task.done():
                pipe.send_bytes(b"\x11")
            await asyncio.wait_for(task, 15)
            assert nav.active.image is None
            assert doc._dataset_handle is None


def test_metadata_first_defaults_borrowing_and_source_cache(stack_file, monkeypatch):
    path, data = stack_file
    import twhy.ome_navigation as ingress
    original, opens = ingress.open_ome_dataset, []
    def counted(*args, **kwargs):
        opens.append((args, kwargs))
        return original(*args, **kwargs)
    monkeypatch.setattr(ingress, "open_ome_dataset", counted)
    doc = ImageDocument(path)
    first = doc.initialize()
    dataset = first.dataset
    try:
        assert first.position == (0, 0, 0) and doc.count == 1
        assert isinstance(first.image, Image)
        np.testing.assert_array_equal(first.image.read_region(3, 12, 4, 15),
                                      data[0, :, 0, 3:12, 4:15])
        later = doc.load_plane(0, z_index=4, t_index=2)
        try:
            assert later.dataset is dataset and len(opens) == 1
            assert later.image.plane_selection != first.image.plane_selection
            np.testing.assert_array_equal(later.image.read_region(3, 12, 4, 15),
                                          data[2, :, 4, 3:12, 4:15])
            first.release()
            assert dataset.is_open and later.image.is_open
            before = dataset.cache_info()["loads"]
            later.image.read_region(3, 12, 4, 15)
            assert dataset.cache_info()["loads"] == before
            # Releasing the document cannot close an active borrowed item.
            doc.close()
            assert dataset.is_open and later.image.is_open
        finally:
            later.release()
        assert not dataset.is_open
    finally:
        if first.image is not None:
            first.release()
        doc.close()


@pytest.mark.parametrize("axes,expected", [("ZYX", ("Z",)), ("TYX", ("T",)),
                                           ("TZYX", ("Z", "T")),
                                           ("TCZYX", ("Z", "T")),
                                           ("YX", ("series",))])
def test_navigation_dimensions_and_default_axis(tmp_path, axes, expected):
    path = tmp_path / f"{axes}.ome.tif"
    write_stack(path, axes=axes)
    doc = ImageDocument(path)
    item = doc.initialize()
    nav = DocumentNavigation(doc, item)
    try:
        assert nav.axes == expected and nav.axis == expected[0]
        assert nav.destination_limits == (0, 4 if expected[0] == "Z" else
                                         2 if expected[0] == "T" else 0)
    finally:
        nav.close()


@pytest.mark.parametrize("options", [{"z_index": 5}, {"t_index": 3},
                                    {"z_index": -1}, {"z_index": True}])
def test_invalid_initial_indices_fail_and_close(tmp_path, options):
    path = tmp_path / "bad.ome.tif"
    write_stack(path)
    doc = ImageDocument(path, **options)
    with pytest.raises((ValueError, IndexError, TypeError)):
        doc.initialize()
    assert doc._dataset_handle is None


@pytest.mark.parametrize("z,t", [(0, 0), (4, 2), (2, 1)])
def test_public_fixed_image_and_cli_snapshot_use_selected_tiff_plane(stack_file, tmp_path, z, t):
    path, data = stack_file
    with open_image(path, z_index=z, t_index=t) as image:
        assert isinstance(image, OMETiffReader)
        np.testing.assert_array_equal(image.read_region(0, 32, 0, 48), data[t, :, z])
    out = tmp_path / f"z{z}-t{t}.txt"
    result = CliRunner().invoke(main, [str(path), "--z-index", str(z), "--t-index", str(t),
                                      "--snapshot", "--columns", "20", "--rows", "8",
                                      "--lower", "0", "--upper", "20000", "-o", str(out)])
    assert result.exit_code == 0, (result.output, result.exception)
    assert len(out.read_text().splitlines()) == 8


def test_cli_default_plane_matches_explicit_zero(stack_file, tmp_path):
    path, _ = stack_file
    outputs = []
    for i, selectors in enumerate(([], ["--z-index", "0", "--t-index", "0"])):
        out = tmp_path / f"{i}.txt"
        result = CliRunner().invoke(main, [str(path), "--snapshot", "--rows", "8",
                                          "--columns", "20", "-o", str(out), *selectors])
        assert result.exit_code == 0, (result.output, result.exception)
        outputs.append(out.read_bytes())
    assert outputs[0] == outputs[1]
    # The explicit, stable-image Python helper retains the strict backend contract.
    with pytest.raises(ValueError):
        with open_image(path):
            pass


def test_view_sessions_never_evict_source_cache_on_channel_level_or_plane(stack_file, monkeypatch):
    from omeify import open_dataset
    path, _ = stack_file
    with open_dataset(path, input_type="ome_tiff") as dataset:
        def forbidden(*args, **kwargs):
            raise AssertionError("twhy must not flush the provider's shared cache")
        monkeypatch.setattr(dataset, "clear_cache", forbidden)
        for z in (0, 1, 0):
            with dataset.plane(z=z, t=0) as image, ViewSession(image, cache_mib=0) as session:
                for channels, size in (((0, 1), 8), ((1, 0), 48), ((0,), 8)):
                    plan = session.plan(Viewport(0, 0, 48, 32), rows=size, columns=size,
                                        channels=channels)
                    session.sample(plan)
                session.step_overview((0, 1))
                session.clear_cache()  # display caches only


async def test_keyboard_z_t_preserves_camera_windows_colors_and_channels(stack_file):
    path, _ = stack_file
    async with browsing_stack(path, channels=(0, 1), channel_colors={1: "cyan"}) as (
        nav, viewer, pipe, _, task
    ):
        await send(pipe, "+\x1b[C", viewer, task)
        camera, windows = viewer.viewport, tuple(viewer.windows)
        colors = tuple(viewer.channel_colors)
        first_samples = viewer.samples.values.copy()
        dataset = nav.active.dataset
        await send(pipe, "]", viewer, task)
        await eventually(lambda: nav.active.z_index == 1 and not viewer.busy, task)
        assert viewer.viewport == camera and tuple(viewer.windows) == windows
        assert tuple(viewer.channel_colors) == colors and viewer.selected_channels == (0, 1)
        assert nav.active.dataset is dataset and "Z 1/4" in nav.status()
        assert not np.array_equal(viewer.samples.values, first_samples)
        await send(pipe, "d", viewer, task)
        assert nav.axis == "T"
        await send(pipe, "p\x01\x0b2\r", viewer, task)
        assert nav.active.position == (0, 1, 2)
        assert viewer.viewport == camera and tuple(viewer.windows) == windows
        await send(pipe, "p\x01\x0b3\r", viewer, task)
        assert viewer.editing == "destination" and "Invalid time point" in viewer.message
        await send(pipe, "\x03", viewer, task)
        assert viewer.editing is None
        await send(pipe, "[", viewer, task)
        assert nav.active.position == (0, 1, 1)
        await send(pipe, "d", viewer, task)
        assert nav.axis == "Z"
        await send(pipe, "p\x01\x0b4\r", viewer, task)
        assert nav.active.z_index == 4
        await send(pipe, "]", viewer, task)
        assert nav.active.z_index == 4 and "No Z plane" in viewer.message


async def test_dimension_clicks_and_sidebar_page_keys(stack_file):
    async with browsing_stack(stack_file[0]) as (nav, viewer, pipe, _, task):
        for _, text, *handler in navigation_fragments(viewer):
            if text.startswith("[T "):
                handler[0](MouseEvent(Point(0, 0), MouseEventType.MOUSE_UP,
                                      MouseButton.LEFT, frozenset()))
                break
        assert nav.axis == "T"
        await send(pipe, "\x1b[6~", viewer, task)
        assert nav.active.t_index == 1
        await send(pipe, "\t\x1b[6~", viewer, task)
        assert viewer.focused_channel == 1 and nav.active.t_index == 1
        await send(pipe, "]", viewer, task)
        assert nav.active.t_index == 2  # brackets remain dimension keys with sidebar focus


async def test_series_resets_but_plane_steps_do_not(tmp_path):
    path = tmp_path / "mixed.ome.tif"
    write_stack(path, extra_series=True)
    async with browsing_stack(path, z_index=4, t_index=2) as (nav, viewer, pipe, _, task):
        owner = nav.active.dataset
        assert nav.axes == ("Z", "T", "series")
        await send(pipe, "dd", viewer, task)
        assert nav.axis == "series"
        await send(pipe, "]", viewer, task)
        assert nav.active.position == (1, 0, 0) and nav.axes == ("series",)
        assert not owner.is_open
        await send(pipe, "[", viewer, task)
        assert nav.active.position == (0, 0, 0)  # startup indices are not reused
        assert viewer.selected_channels == (0,)


async def test_rapid_cross_axis_requests_discard_obsolete_loads(stack_file, monkeypatch):
    async with browsing_stack(stack_file[0]) as (nav, viewer, _, _, task):
        original = nav.document.load_plane
        started, release = threading.Event(), threading.Event()
        loaded = []
        def delayed(index, **kwargs):
            if kwargs["z_index"] == 1:
                started.set()
                assert release.wait(5)
            item = original(index, **kwargs)
            loaded.append(item)
            return item
        monkeypatch.setattr(nav.document, "load_plane", delayed)
        try:
            nav.go_plane(z_index=1, t_index=0)
            await eventually(started.is_set, task)
            assert nav.active.position == (0, 0, 0)
            assert "opening series 0 Z=1 T=0" in nav.status()
            for z, t in ((2, 0), (3, 1), (4, 2)):
                nav.go_plane(z_index=z, t_index=t)
            release.set()
            await eventually(lambda: nav.active.position == (0, 4, 2) and not viewer.busy, task)
            assert len(loaded) == 2 and loaded[0].image is None
            np.testing.assert_array_equal(nav.active.image.read_region(0, 2, 0, 2),
                                          stack_file[1][2, :, 4, :2, :2])
        finally:
            release.set()


async def test_failed_plane_load_retains_previous_view(stack_file, monkeypatch):
    async with browsing_stack(stack_file[0]) as (nav, viewer, _, _, task):
        old, camera = nav.active, viewer.viewport
        def failed(*args, **kwargs):
            raise OSError("deliberate missing plane")
        monkeypatch.setattr(nav.document, "load_plane", failed)
        nav.go_plane(z_index=2, t_index=0)
        await eventually(lambda: "missing plane" in nav.error, task)
        await ready(viewer, task)
        assert nav.active is old and nav.target_position == old.position
        assert viewer.viewport == camera and old.dataset.is_open


async def test_selection_freezes_all_navigation(stack_file, monkeypatch):
    # Isolate naming, not image I/O: use a fixed identity while exercising the
    # actual selection controller and real source lifetime/navigation behavior.
    async with browsing_stack(stack_file[0]) as (nav, viewer, pipe, _, task):
        from twhy.annotation_identity import AnnotationIdentity
        monkeypatch.setattr(viewer.clipping.identities, "create",
                            lambda: AnnotationIdentity("test-id", "test-plane-area", True))
        await send(pipe, "s", viewer, task)
        assert viewer.selecting
        before = nav.active.position
        nav.go_plane(z_index=4, t_index=2)
        nav.cycle_axis()
        pipe.send_text("d]")
        await asyncio.sleep(.12)
        assert nav.active.position == before and nav.axis == "Z"
        await send(pipe, "s", viewer, task)
        await send(pipe, "]", viewer, task)
        assert nav.active.z_index == 1


@pytest.mark.parametrize("axes", ["TZYXS", "ZYXS", "TYXS"])
def test_rgb_stacks_keep_one_logical_channel(tmp_path, axes):
    path = tmp_path / f"{axes}.ome.tif"
    data = write_stack(path, axes=axes, rgb=True)
    doc = ImageDocument(path)
    item = doc.initialize()
    try:
        assert item.image.axes == "YXS" and item.image.channel_count == 1
        selection = tuple(0 if a in "TZ" else slice(None) for a in axes)
        np.testing.assert_array_equal(item.image.asarray(), data[selection])
    finally:
        item.release()
        doc.close()


async def test_plane_handoff_waits_for_display_read_and_discards_stale_frame(
    stack_file, monkeypatch,
):
    from twhy.viewer import viewer as viewer_module
    async with browsing_stack(stack_file[0]) as (nav, viewer, _, _, task):
        original = viewer_module.make_frame
        entered, release = threading.Event(), threading.Event()
        old_item, old_image, old_session = nav.active, nav.active.image, viewer.session
        finished = []

        def blocked(session, request):
            if session is old_session:
                entered.set()
                assert release.wait(5)
                assert old_image.is_open and old_item.dataset.is_open
            result = original(session, request)
            finished.append((session, request.generation))
            return result

        monkeypatch.setattr(viewer_module, "make_frame", blocked)
        try:
            viewer.pan_cells(1, 0)
            await eventually(entered.is_set, task)
            nav.go_plane(z_index=4, t_index=2)
            await eventually(lambda: nav.pending is not None, task)
            assert nav.active is old_item and old_image.is_open
            release.set()
            await eventually(lambda: nav.active.position == (0, 4, 2) and not viewer.busy, task)
            await ready(viewer, task)
            assert old_item.image is None and not old_image.is_open
            assert finished[0][1] != viewer.displayed_generation
            assert finished[-1][0] is viewer.session
        finally:
            release.set()


async def test_quit_joins_plane_loader_before_closing_dataset(stack_file, monkeypatch):
    async with browsing_stack(stack_file[0]) as (nav, viewer, pipe, _, task):
        dataset, original = nav.active.dataset, nav.document.load_plane
        entered, release = threading.Event(), threading.Event()
        loaded = []

        def blocked(index, **kwargs):
            entered.set()
            assert release.wait(5)
            assert dataset.is_open
            item = original(index, **kwargs)
            loaded.append(item)
            return item

        monkeypatch.setattr(nav.document, "load_plane", blocked)
        try:
            nav.go_plane(z_index=1, t_index=0)
            await eventually(entered.is_set, task)
            pipe.send_text("q")
            await asyncio.sleep(.1)
            assert not task.done() and dataset.is_open
            release.set()
            await asyncio.wait_for(asyncio.shield(task), 8)
            assert not dataset.is_open and loaded[0].image is None
        finally:
            release.set()


def test_discarded_series_load_does_not_evict_current_dataset(tmp_path):
    path = tmp_path / "discarded.ome.tif"
    write_stack(path, extra_series=True)
    doc = ImageDocument(path)
    first = doc.initialize()
    original_dataset = first.dataset
    stale = second = None
    try:
        first.image.read_region(0, 8, 0, 8)
        loads = original_dataset.cache_info()["loads"]
        stale = doc.load(1)
        stale_dataset = stale.dataset
        stale.release()
        stale = None
        assert not stale_dataset.is_open and original_dataset.is_open
        second = doc.load_plane(0, z_index=0, t_index=0)
        assert second.dataset is original_dataset
        second.image.read_region(0, 8, 0, 8)
        assert original_dataset.cache_info()["loads"] == loads
    finally:
        if stale is not None:
            stale.release()
        if second is not None:
            second.release()
        first.release()
        doc.close()


async def test_keyboard_jump_in_fullscreen_and_without_sidebar(stack_file):
    async with browsing_stack(stack_file[0]) as (nav, viewer, pipe, _, task):
        await send(pipe, "f", viewer, task)
        assert viewer.image_only
        await send(pipe, "dp\x01\x0b2\r", viewer, task)
        assert nav.axis == "T" and nav.active.t_index == 2
        await send(pipe, "f", viewer, task)
        assert not viewer.image_only
        await send(pipe, "cd]", viewer, task)
        assert nav.axis == "Z" and nav.active.z_index == 1


@pytest.mark.parametrize("axes", ["TCZYX", "TZCYX", "CTZYX", "CZTYX", "ZTCYX", "ZCTYX"])
def test_tiff_plane_selection_in_all_dimension_orders(tmp_path, axes):
    path = tmp_path / f"{axes}.ome.tif"
    values = write_stack(path, axes=axes)
    doc = ImageDocument(path, t_index=2, z_index=4)
    item = doc.initialize()
    try:
        selection = tuple(2 if a == "T" else 4 if a == "Z" else slice(None) for a in axes)
        np.testing.assert_array_equal(item.image.read_region(0, 32, 0, 48), values[selection])
    finally:
        item.release()
        doc.close()


def test_older_omeify_fails_with_branch_install_hint(stack_file, monkeypatch):
    import omeify
    monkeypatch.delattr(omeify, "open_dataset")
    doc = ImageDocument(stack_file[0])
    with pytest.raises(RuntimeError, match="updated Omeify z_t_support checkout"):
        doc.initialize()
    assert doc._dataset_handle is None


@pytest.mark.parametrize("keyword", ["z_index", "t_index"])
def test_raster_rejects_ome_plane_flags(tmp_path, keyword):
    from PIL import Image as PillowImage
    path = tmp_path / "photo.png"
    PillowImage.new("RGB", (8, 8)).save(path)
    with pytest.raises(ValueError, match="OME-TIFF and OME-Zarr"):
        ImageDocument(path, **{keyword: 0})
    with pytest.raises(ValueError, match="OME-TIFF and OME-Zarr"):
        with open_image(path, **{keyword: 0}):
            pass


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX terminal test")
def test_zt_real_terminal_navigation_and_restoration(stack_file):
    import io
    import os
    import sys
    import time
    pexpect = pytest.importorskip("pexpect")
    transcript = io.StringIO()
    terminal = pexpect.spawn(
        sys.executable, ["-m", "twhy", str(stack_file[0]), "--overview-cache-mib", "0"],
        encoding="utf-8", timeout=15, dimensions=(28, 110),
        env={**os.environ, "TERM": "xterm-256color", "COLORTERM": "truecolor"})
    terminal.logfile_read = transcript
    try:
        terminal.expect(r"Z 0/4")
        terminal.expect("d:axis")
        terminal.send("]")
        terminal.expect("Plane changed")
        terminal.send("dp\x01\x0b2\r")
        time.sleep(.25)
        terminal.setwinsize(29, 111)  # force a full redraw rather than matching ANSI diffs
        terminal.expect(r"T 2/2")
        terminal.send("q")
        terminal.expect(pexpect.EOF)
    finally:
        terminal.close(force=True)
    output = transcript.getvalue()
    assert terminal.exitstatus == 0, output
    assert "Traceback" not in output
    assert "\x1b[?1049h" in output and "\x1b[?1049l" in output
    assert "\x1b[?1006h" in output and "\x1b[?1006l" in output
    assert "\x1b[?25h" in output
