"""Real Pillow GIFs and Omeify time planes in the existing terminal/render pipeline."""

import asyncio
from contextlib import asynccontextmanager

import numpy as np
import pytest
from click.testing import CliRunner
from PIL import Image
from prompt_toolkit.input import create_pipe_input

from test_viewer import SizedOutput, eventually, ready
from test_zt_navigation import write_stack
from twhy import IntensityWindow, TextRenderer
from twhy.cli import main
from twhy.image_document import ImageDocument
from twhy.raster_animation import GIFAnimation, is_gif
from twhy.viewer import Viewer
from twhy.viewer.navigation import DocumentNavigation
from twhy.viewer.playback import playback_rate


def write_gif(path, *, durations=(160, 230, 170)):
    colors = [(245, 30, 10), (20, 220, 40), (20, 50, 230)]
    frames = [Image.new("RGB", (36, 24), c) for c in colors]
    frames[0].save(path, save_all=True, append_images=frames[1:], loop=0,
                   duration=list(durations), disposal=2, optimize=False, format="GIF")
    return colors


@asynccontextmanager
async def browsing(path, *, fps=None, autoplay=None, frame=None):
    doc = ImageDocument(path, frame=frame)
    initial = doc.initialize()
    nav = DocumentNavigation(doc, initial, overview_cache_mib=0)
    with create_pipe_input() as pipe:
        viewer = Viewer(nav.session, navigation=nav, renderer=TextRenderer(mode="blocks"),
                        window=IntensityWindow(0, 255) if doc.kind == "gif" else
                        IntensityWindow(0, 40000),
                        play_fps=fps, autoplay=autoplay)
        output = SizedOutput()
        task = asyncio.create_task(viewer.run(input=pipe, output=output))
        try:
            await ready(viewer, task)
            yield doc, nav, viewer, pipe, task
        finally:
            if not task.done():
                pipe.send_bytes(b"\x11")
            await asyncio.wait_for(task, 15)
            assert nav.active.image is None
            assert doc.animation is None or not doc.animation._image.fp


def test_gif_lru_compositing_lifetimes_and_real_delays(tmp_path):
    path = tmp_path / "animation.bin"  # actual file signature, not suffix
    expected = write_gif(path, durations=(0, 120, 300))
    assert is_gif(path)
    animation = GIFAnimation(path, cache_mib=0.004)
    assert animation.count == 3
    held = animation.arrays(0)
    assert len(held) >= 2 and not held[0].flags.writeable
    np.testing.assert_allclose(held[0][10, 10], expected[0], atol=12)
    assert animation.duration(0) == 0.04
    for index in (1, 2):
        pixels = animation.arrays(index)[0]
        np.testing.assert_allclose(pixels[10, 10], expected[index], atol=12)
    assert animation.duration(1) == .12 and animation.duration(2) == .3
    assert animation.cached_bytes <= animation.limit
    assert len(animation.cached_frames) < 3
    np.testing.assert_allclose(animation.arrays(0)[0][10, 10], expected[0], atol=12)
    animation.close()
    animation.close()
    np.testing.assert_allclose(held[0][10, 10], expected[0], atol=12)
    with pytest.raises(RuntimeError, match="closed"):
        animation.arrays(0)


def test_document_animates_only_multi_frame_gifs(tmp_path):
    path = tmp_path / "gif-with-no-extension"
    write_gif(path)
    doc = ImageDocument(path, frame=2)
    initial = doc.initialize()
    try:
        assert doc.kind == "gif" and doc.count == 3 and doc.label == "frame"
        assert initial.position == (2, None, None)
        assert "frame 2/2" in doc.item_name(initial)
        before = initial.image.read_region(1, 5, 2, 8)
        later = doc.load(0)
        try:
            assert not np.array_equal(before, later.image.read_region(1, 5, 2, 8))
        finally:
            later.release()
    finally:
        initial.release()
        doc.close()
    with pytest.raises(ValueError, match="frame"):
        ImageDocument(path, series=1)
    single = tmp_path / "single.gif"
    Image.new("RGB", (24, 16), "red").save(single)
    doc = ImageDocument(single)
    assert doc.kind == "raster"
    doc.close()


@pytest.mark.parametrize("fps", [0, -5, 30.1, float("nan"), float("inf"), True])
def test_reject_impossible_playback_rates(fps):
    with pytest.raises(ValueError, match="FPS"):
        playback_rate(fps)
    assert playback_rate(None) is None
    assert playback_rate(2.5) == 2.5


def test_snapshot_remains_single_frame_and_cli_flags_validate(tmp_path):
    path = tmp_path / "animated.gif"
    write_gif(path)
    out = tmp_path / "frame.txt"
    result = CliRunner().invoke(main, [str(path), "--frame", "2", "--snapshot", "-o", str(out)])
    assert result.exit_code == 0, (result.output, result.exception)
    assert out.is_file()
    for option in ("--autoplay", "--no-autoplay", "--play-fps=3"):
        result = CliRunner().invoke(main, [str(path), "--snapshot", option])
        assert result.exit_code != 0 and "interactive viewing" in result.output


async def test_gif_autoplays_loops_and_manual_step_pauses(tmp_path):
    path = tmp_path / "loop.gif"
    write_gif(path)
    async with browsing(path) as (doc, nav, viewer, pipe, task):
        assert viewer.playback.playing and nav.axes == ("frame",)
        assert nav.active.index == 0
        assert viewer.playback.rate_label == "GIF delay"
        await eventually(lambda: nav.active.index == 1 and not viewer.busy, task)
        await eventually(lambda: nav.active.index == 2 and not viewer.busy, task)
        await eventually(lambda: nav.active.index == 0 and not viewer.busy, task)
        assert doc.animation.cached_bytes > 0
        pipe.send_text("P")
        await eventually(lambda: not viewer.playback.playing, task)
        fixed = nav.active.index
        await asyncio.sleep(.5)
        assert nav.active.index == fixed
        if fixed == 2:
            pipe.send_text("[")
            expected = 1
        else:
            pipe.send_text("]")
            expected = fixed + 1
        await eventually(lambda: nav.active.index == expected, task)
        # Bracket navigation is bounded; only playback wraps.
        assert not viewer.playback.playing
        pipe.send_text("R")
        await eventually(lambda: viewer.editing == "play-fps", task)
        pipe.send_bytes(b"\x01\x0b")  # Select/delete prefilled rate.
        pipe.send_text("7\r")
        await eventually(lambda: viewer.editing is None and viewer.playback.fps == 7, task)
        pipe.send_text("P")
        await eventually(lambda: viewer.playback.playing, task)


async def test_gif_explicit_paused_frame_and_no_blank_transition(tmp_path):
    path = tmp_path / "paused.gif"
    write_gif(path)
    async with browsing(path, autoplay=False, frame=1) as (_, nav, viewer, pipe, task):
        assert nav.active.index == 1 and not viewer.playback.playing
        frame = viewer.frame
        position, status = nav.display_position, nav.presented_name
        pipe.send_text("]")
        await eventually(lambda: nav.active.index == 2 and not viewer.busy, task)
        assert nav.presented_name != status
        assert nav.display_position != position
        assert frame is not None
        pipe.send_text("[")
        await eventually(lambda: nav.active.index == 1 and not viewer.busy, task)
        assert nav.presented_name == status


async def test_ome_time_slideshow_keeps_z_and_windows_and_loops(tmp_path):
    path = tmp_path / "time.ome.tif"
    write_stack(path)
    async with browsing(path, fps=9) as (_, nav, viewer, pipe, task):
        assert viewer.playback.available and viewer.playback.kind == "time"
        assert not viewer.playback.playing and nav.active.z_index == 2
        initial_window = viewer.windows[0]
        initial_camera = viewer.viewport
        pipe.send_text("P")
        await eventually(lambda: nav.active.t_index == 1 and not viewer.busy, task)
        await eventually(lambda: nav.active.t_index == 2 and not viewer.busy, task)
        await eventually(lambda: nav.active.t_index == 0 and not viewer.busy, task)
        assert nav.axis == "T" and nav.active.z_index == 2
        assert viewer.windows[0] == initial_window and viewer.viewport == initial_camera
        pipe.send_text("P")
        await eventually(lambda: not viewer.playback.playing, task)
        old = nav.active.t_index
        await asyncio.sleep(.3)
        assert nav.active.t_index == old


async def test_manual_ome_navigation_pauses_playback(tmp_path):
    path = tmp_path / "time.ome.tif"
    write_stack(path)
    async with browsing(path, fps=1) as (_, nav, viewer, pipe, task):
        viewer.playback.toggle()
        assert viewer.playback.playing
        pipe.send_text("d")
        await eventually(lambda: not viewer.playback.playing, task)
        assert nav.axis == "T" or nav.axis == "Z"

async def test_slow_gif_decode_retains_completed_frame_and_does_not_skip(tmp_path, monkeypatch):
    from threading import Event

    path = tmp_path / "slow.gif"
    write_gif(path, durations=(100, 100, 100))
    async with browsing(path, fps=12, autoplay=False) as (doc, nav, viewer, _, task):
        before = viewer.frame
        name = nav.presented_name
        camera, window = viewer.viewport, tuple(viewer.windows)
        entered, gate = Event(), Event()
        original = doc.animation.arrays

        def delayed(index):
            if index == 1:
                entered.set()
                if not gate.wait(4):
                    raise RuntimeError("Synthetic read gate failed")
            return original(index)

        monkeypatch.setattr(doc.animation, "arrays", delayed)
        viewer.playback.toggle()
        try:
            await eventually(entered.is_set, task)
            await asyncio.sleep(.2)  # Slower than several requested frame intervals.
            assert nav.active.index == 0 and nav.target == 1
            assert viewer.frame is before and nav.presented_name == name
            assert viewer.playback.playing
            assert doc.animation.cached_bytes <= doc.animation.limit
        finally:
            gate.set()
        await eventually(lambda: nav.active.index == 1 and nav.display_position[0] == 1,
                         task, timeout=5)
        assert viewer.viewport == camera and tuple(viewer.windows) == window
        assert nav.presented_name != name


async def test_playback_pauses_for_selection_and_histogram(tmp_path, monkeypatch):
    path = tmp_path / "select.gif"
    write_gif(path, durations=(300, 300, 300))
    async with browsing(path) as (_, nav, viewer, pipe, task):
        from twhy.annotation_identity import AnnotationIdentity
        monkeypatch.setattr(viewer.clipping.identities, "create",
                            lambda: AnnotationIdentity("test-id", "test-selection"))
        assert viewer.playback.playing
        pipe.send_text("H")
        await eventually(lambda: viewer.histogram_mode, task)
        assert not viewer.playback.playing
        pipe.send_text("H")
        await eventually(lambda: not viewer.histogram_mode, task)
        # A long dwell keeps the current frame stable while selection starts.
        viewer.playback.set_fps(0.1)
        pipe.send_text("P")
        await eventually(lambda: viewer.playback.playing, task)
        await ready(viewer, task)
        pipe.send_text("s")
        await eventually(lambda: viewer.selecting, task)
        assert not viewer.playback.playing
        pipe.send_bytes(b"\x1b")
        await eventually(lambda: not viewer.selecting, task)
        assert not viewer.playback.playing


def test_gif_disposal_transparency_matches_pillow_composited_frames(tmp_path):
    from twhy.image_input import _raster_pixels

    path = tmp_path / "disposal.gif"
    originals = [Image.new("RGBA", (32, 24), (0, 0, 0, 0)) for _ in range(3)]
    for image, color, dx in zip(originals, ("red", "green", "blue"), (2, 10, 19)):
        from PIL import ImageDraw
        ImageDraw.Draw(image).rectangle((dx, 3, dx + 5, 10), fill=color)
    originals[0].save(path, save_all=True, append_images=originals[1:],
                      format="GIF", optimize=True, duration=[90, 160, 230],
                      loop=0, disposal=[1, 2, 1])
    animation = GIFAnimation(path, background=(255, 255, 255))
    try:
        for frame in (0, 1, 2, 0, 2, 1):
            # Independent fresh Pillow decoder per position; GIF logical frame,
            # not a raw subrectangle or raw palette index.
            np.testing.assert_array_equal(animation.arrays(frame)[0],
                                          _raster_pixels(path, frame, (255, 255, 255)))
    finally:
        animation.close()


async def test_clickable_play_button_and_rate_editor_are_real_controls(tmp_path):
    from prompt_toolkit.data_structures import Point
    from prompt_toolkit.mouse_events import MouseButton, MouseEvent, MouseEventType
    from twhy.viewer.controls import navigation_fragments

    path = tmp_path / "buttons.gif"
    write_gif(path)
    async with browsing(path, autoplay=False) as (_, nav, viewer, pipe, task):
        fragments = navigation_fragments(viewer)
        play = next(handler for _, text, handler in fragments if "▶ P" in text)
        play(MouseEvent(Point(0, 0), MouseEventType.MOUSE_UP,
                        MouseButton.LEFT, frozenset()))
        assert viewer.playback.playing
        fragments = navigation_fragments(viewer)
        assert any("Ⅱ P" in text for _, text, *_ in fragments)
        play = next(handler for _, text, handler in fragments if "Ⅱ P" in text)
        play(MouseEvent(Point(0, 0), MouseEventType.MOUSE_UP,
                        MouseButton.LEFT, frozenset()))
        assert not viewer.playback.playing
        rate = next(handler for _, text, handler in navigation_fragments(viewer)
                    if "R: GIF delay" in text)
        rate(MouseEvent(Point(0, 0), MouseEventType.MOUSE_UP,
                        MouseButton.LEFT, frozenset()))
        assert viewer.editing == "play-fps"
        pipe.send_bytes(b"\x01\x0b")
        pipe.send_text("6\r")
        await eventually(lambda: viewer.editing is None, task)
        assert viewer.playback.fps == 6


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="POSIX PTY test")
def test_real_gif_cli_terminal_loops_and_restores_terminal(tmp_path):
    import io
    import os
    import sys
    pexpect = pytest.importorskip("pexpect")

    path = tmp_path / "terminal.gif"
    write_gif(path, durations=(200, 200, 200))
    env = {**os.environ, "TERM": "xterm-256color", "COLORTERM": "truecolor"}
    env.pop("NO_COLOR", None)
    env.pop("PROMPT_TOOLKIT_COLOR_DEPTH", None)
    terminal = pexpect.spawn(sys.executable,
                             ["-m", "twhy", str(path), "--play-fps", "5"],
                             env=env, encoding="utf-8", timeout=15,
                             dimensions=(27, 105))
    transcript = io.StringIO()
    terminal.logfile_read = transcript
    try:
        terminal.expect("frame 0/2")
        # Terminal diff output can update just changed characters of the title.
        # The next GIF frame is green; look for its real truecolor cell output.
        terminal.expect("48;2;20;220;40")
        terminal.send("P")
        terminal.send("q")
        terminal.expect(pexpect.EOF)
    finally:
        terminal.close(force=True)
    output = transcript.getvalue()
    assert terminal.exitstatus == 0, output[-1500:]
    assert "Traceback" not in output
    assert "\x1b[?1049h" in output and "\x1b[?1049l" in output
    assert "\x1b[?1006l" in output and "\x1b[?25h" in output


async def test_failed_gif_read_pauses_and_keeps_previous_frame(tmp_path, monkeypatch):
    path = tmp_path / "broken-later.gif"
    write_gif(path)
    async with browsing(path, fps=15, autoplay=False) as (doc, nav, viewer, _, task):
        previous_frame = viewer.frame
        previous_title = nav.presented_name
        original = doc.animation.arrays

        def fail_later(index):
            if index == 1:
                raise OSError("deliberate damaged GIF frame")
            return original(index)

        monkeypatch.setattr(doc.animation, "arrays", fail_later)
        viewer.playback.toggle()
        await eventually(lambda: not viewer.playback.playing and bool(nav.error), task)
        assert "deliberate damaged GIF frame" in nav.error
        assert nav.active.index == 0 and nav.presented_name == previous_title
        assert viewer.frame is previous_frame
        assert viewer.application.is_running


async def test_gif_mouse_drag_survives_playback_frame_handoffs(tmp_path):
    """Real SGR mouse press/moves remain one gesture across GIF frame publication."""
    from prompt_toolkit.data_structures import Point

    path = tmp_path / "drag-during-playback.gif"
    write_gif(path, durations=(330, 330, 330))
    async with browsing(path, fps=2, autoplay=True) as (_, nav, viewer, pipe, task):
        original = viewer.viewport
        # SGR mouse coordinates are terminal-cell based and one-indexed. The
        # image canvas starts after the title and document-navigation rows.
        pipe.send_bytes(b"\x1b[<64;35;12M")  # Pointer-anchored zoom.
        await eventually(lambda: viewer.viewport.width < original.width, task)
        pipe.send_bytes(b"\x1b[<0;35;12M")  # Press at canvas cell (34, 9).
        await eventually(lambda: viewer.canvas._drag == Point(34, 9), task)
        before = viewer.viewport
        await eventually(lambda: nav.display_position[0] != 0, task, timeout=5)
        assert viewer.playback.playing
        assert viewer.canvas._drag == Point(34, 9)

        # The terminal only sends one MOUSE_DOWN for the entire gesture.
        pipe.send_bytes(b"\x1b[<32;29;13M")  # Move while held to (28, 10).
        await eventually(lambda: viewer.canvas._drag == Point(28, 10), task)
        assert viewer.viewport.x > before.x
        assert viewer.viewport.y < before.y
        after_one_move = viewer.viewport

        current_frame = nav.display_position[0]
        await eventually(lambda: nav.display_position[0] != current_frame, task, timeout=5)
        assert viewer.canvas._drag == Point(28, 10)
        pipe.send_bytes(b"\x1b[<32;25;13M")  # Still held: move again.
        await eventually(lambda: viewer.canvas._drag == Point(24, 10), task)
        assert viewer.viewport.x > after_one_move.x
        assert viewer.playback.playing

        pipe.send_bytes(b"\x1b[<0;25;13m")
        await eventually(lambda: viewer.canvas._drag is None, task)
        last_view = viewer.viewport
        pipe.send_bytes(b"\x1b[<32;19;13M")  # No press: must not pan.
        await asyncio.sleep(.04)
        assert viewer.viewport == last_view


async def test_ome_t_mouse_drag_survives_playback_frame_handoffs(tmp_path):
    """T playback preserves the same in-progress pan across time points."""
    from prompt_toolkit.data_structures import Point
    from prompt_toolkit.mouse_events import MouseButton, MouseEvent, MouseEventType

    path = tmp_path / "drag-time.ome.tif"
    write_stack(path)
    async with browsing(path, fps=2, autoplay=True) as (_, nav, viewer, _, task):
        def mouse(kind, x, y):
            viewer.canvas.mouse_handler(MouseEvent(
                Point(x, y), kind, MouseButton.LEFT, frozenset()))

        viewer.zoom(1.5)
        mouse(MouseEventType.MOUSE_DOWN, 25, 9)
        assert viewer.canvas._drag == Point(25, 9)
        await eventually(lambda: nav.display_position[2] != 0, task, timeout=5)
        assert viewer.canvas._drag == Point(25, 9)
        before = viewer.viewport
        mouse(MouseEventType.MOUSE_MOVE, 20, 11)
        assert viewer.viewport.x > before.x and viewer.viewport.y < before.y
        assert viewer.canvas._drag == Point(20, 11)
        assert viewer.playback.playing
        mouse(MouseEventType.MOUSE_UP, 20, 11)
        assert viewer.canvas._drag is None
