"""Real prompt_toolkit interactions, fixed windows, and atomic plane presentation."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import threading

import pytest
from prompt_toolkit.data_structures import Point, Size
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.mouse_events import MouseButton, MouseEvent, MouseEventType

from twhy import ContrastConfig, IntensityWindow, TextRenderer
from twhy.image_document import ImageDocument
from twhy.viewer import Viewer
from twhy.viewer.navigation import DocumentNavigation
from test_viewer import SizedOutput, eventually, ready
from test_zt_navigation import write_stack


FAST = ContrastConfig(draws=24, tile_size=8, max_base_samples=8192,
                      survey_reads=8, survey_samples=8192, bootstrap_replicates=0)


@asynccontextmanager
async def contrast_view(path, *, automatic=False, window=IntensityWindow(0, 20000), config=FAST):
    doc = ImageDocument(path)
    initial = doc.initialize()
    nav = DocumentNavigation(doc, initial, window=window, cache_mib=0, overview_cache_mib=0)
    with create_pipe_input() as pipe:
        viewer = Viewer(nav.session, navigation=nav, renderer=TextRenderer(mode='blocks'),
                        channels=(0, 1), window=window, stack_contrast=automatic,
                        contrast_config=config)
        output = SizedOutput()
        task = asyncio.create_task(viewer.run(input=pipe, output=output))
        try:
            await ready(viewer, task)
            yield viewer, nav, pipe, output, task
        finally:
            if not task.done():
                pipe.send_bytes(b'\x11')
            await asyncio.wait_for(task, 10)
            assert viewer.contrast.job is None and viewer.contrast.owner is None
            assert doc._dataset_handle is None


@pytest.fixture
def stack(tmp_path):
    path = tmp_path / 'stack.ome.tif'
    write_stack(path, extra_series=True)
    return path


async def histogram_ready(viewer, task, channel=0):
    await eventually(lambda: channel in viewer.contrast.results, task)
    viewer.canvas.create_content(*viewer.canvas_size)
    assert viewer.contrast.plot is not None


def mouse(viewer, kind, x, y):
    viewer.canvas.mouse_handler(MouseEvent(Point(x, y), kind, MouseButton.LEFT, frozenset()))


async def test_histogram_keys_drag_channel_focus_and_no_reads_after_sampling(stack):
    async with contrast_view(stack) as (viewer, nav, pipe, _, task):
        camera, selected = viewer.viewport, viewer.selected_channels
        original_frame = viewer.frame
        pipe.send_text('H')
        await eventually(lambda: viewer.histogram_mode, task)
        await histogram_ready(viewer, task)
        assert viewer.viewport == camera and viewer.frame is original_frame
        plot = viewer.contrast.plot
        assert 'HISTOGRAM' in plot.frame.to_text()
        counts_before = nav.active.dataset.cache_info()['loads']
        result = viewer.contrast.results[0]
        target = plot.left + (plot.upper_column - plot.left) // 2
        mouse(viewer, MouseEventType.MOUSE_DOWN, plot.upper_column, plot.handle_row)
        mouse(viewer, MouseEventType.MOUSE_MOVE, target, plot.handle_row)
        mouse(viewer, MouseEventType.MOUSE_UP, target, plot.handle_row)
        assert viewer.windows[0].upper == pytest.approx(plot.value_at(target))
        assert viewer.windows[0].upper < 20000 and 0 in viewer.contrast.manual
        assert viewer.viewport == camera
        assert nav.active.dataset.cache_info()['loads'] == counts_before
        # Numeric edit uses the same windows, not a second histogram-specific range.
        pipe.send_text('u\x01\x0b12345\r')
        await eventually(lambda: viewer.windows[0].upper == 12345 and viewer.editing is None, task)
        pipe.send_text('L')
        await eventually(lambda: not viewer.contrast.log_counts, task)
        assert viewer.contrast.results[0] is result
        # A cached recommendation is deliberately applied; it performs no sampling.
        pipe.send_text('A')
        await eventually(lambda: viewer.windows[0].upper == result.window.upper, task)
        assert nav.active.dataset.cache_info()['loads'] == counts_before
        pipe.send_text('.')
        await eventually(lambda: viewer.focused_channel == 1, task)
        await histogram_ready(viewer, task, 1)
        assert 'C1:' in viewer.contrast.plot.frame.to_text()
        assert viewer.selected_channels == selected
        # Selection/export cannot reinterpret histogram cells as image-space ROIs.
        pipe.send_text('sv')
        await asyncio.sleep(.08)
        assert not viewer.selecting
        pipe.send_text('H')
        await eventually(lambda: not viewer.histogram_mode, task)
        await ready(viewer, task)
        assert viewer.viewport == camera


async def test_histogram_resize_and_sidebar_click_preserve_image_camera(stack):
    async with contrast_view(stack) as (viewer, _, pipe, output, task):
        camera = viewer.viewport
        pipe.send_text('H')
        await histogram_ready(viewer, task)
        viewer.channel_control.create_content(31, 24)
        row = viewer.channel_control.channel_row_start + 1
        viewer.channel_control.mouse_handler(MouseEvent(
            Point(4, row), MouseEventType.MOUSE_UP, MouseButton.LEFT, frozenset()))
        await histogram_ready(viewer, task, 1)
        assert viewer.focused_channel == 1
        output.size = Size(rows=18, columns=50)
        viewer.application._on_resize()
        await eventually(lambda: viewer.canvas_size[0] == 50, task)
        viewer.canvas.create_content(*viewer.canvas_size)
        assert viewer.viewport == camera
        pipe.send_text('H')
        await eventually(lambda: not viewer.histogram_mode, task)
        await ready(viewer, task)
        assert viewer.viewport == camera


async def test_auto_estimate_applied_once_and_kept_over_z_t_and_pan(stack):
    async with contrast_view(stack, automatic=True, window=None) as (viewer, nav, pipe, _, task):
        await eventually(lambda: len(viewer.contrast.results) == 2 and viewer.contrast.job is None,
                         task)
        await ready(viewer, task)
        estimates = dict(viewer.contrast.results)
        windows = tuple(viewer.windows)
        assert tuple(estimate.window for estimate in estimates.values()) == windows
        assert nav.active.z_index == 2 and nav.active.t_index == 0
        pipe.send_text(']')
        await eventually(lambda: nav.display_position == (0, 3, 0), task)
        await ready(viewer, task)
        nav.select_axis('T')
        pipe.send_text(']')
        await eventually(lambda: nav.display_position == (0, 3, 1), task)
        await ready(viewer, task)
        viewer.zoom(1.25)
        await ready(viewer, task)
        assert tuple(viewer.windows) == windows
        assert all(viewer.contrast.results[c] is estimates[c] for c in estimates)
        assert viewer.contrast.job is None


async def test_manual_edit_wins_over_inflight_automatic_estimate(stack, monkeypatch):
    import twhy.contrast_sampling as sampling
    original = sampling.ContrastEstimator.step
    entered, release = threading.Event(), threading.Event()
    def delayed(job):
        if not entered.is_set():
            entered.set()
            assert release.wait(5)
        return original(job)
    monkeypatch.setattr(sampling.ContrastEstimator, 'step', delayed)
    async with contrast_view(stack, automatic=True, window=None) as (viewer, _, pipe, _, task):
        try:
            await eventually(entered.is_set, task)
            pipe.send_text('u\x01\x0b18000\r')
            await eventually(lambda: viewer.windows[0].upper == 18000, task)
        finally:
            release.set()
        await eventually(lambda: 0 in viewer.contrast.results, task)
        assert viewer.windows[0].upper == 18000 and 0 in viewer.contrast.manual


async def test_explicit_window_not_automatically_replaced_and_histogram_does_not_apply(stack):
    async with contrast_view(stack, automatic=True) as (viewer, _, pipe, _, task):
        await asyncio.sleep(.1)
        assert not viewer.contrast.results and viewer.contrast.job is None
        pipe.send_text('H')
        await histogram_ready(viewer, task)
        assert viewer.windows[0] == IntensityWindow(0, 20000)


async def test_loading_plane_retains_grid_and_matching_label_until_frame_ready(stack, monkeypatch):
    import twhy.viewer.viewer as runtime
    original = runtime.make_frame
    entered, release = threading.Event(), threading.Event()
    async with contrast_view(stack) as (viewer, nav, pipe, _, task):
        old_frame, old_lines, old_name = viewer.frame, viewer.cell_lines, nav.presented_name
        def delayed(session, request):
            selection = session._image.plane_selection
            if selection.z == 3:
                entered.set()
                assert release.wait(5)
            return original(session, request)
        monkeypatch.setattr(runtime, 'make_frame', delayed)
        try:
            pipe.send_text(']')
            await eventually(entered.is_set, task)
            assert nav.active.z_index == 3 and nav.display_position == (0, 2, 0)
            assert viewer.frame is old_frame and viewer.cell_lines is old_lines
            assert nav.presented_name == old_name and old_name in viewer._title()
            assert viewer.samples is None
            assert viewer.canvas.create_content(*viewer.canvas_size).get_line(0)
        finally:
            release.set()
        await eventually(lambda: nav.display_position == (0, 3, 0), task)
        await ready(viewer, task)
        assert viewer.frame is not old_frame and nav._rollback is None


async def test_failed_new_plane_pixels_restore_previous_usable_observation(stack, monkeypatch):
    import twhy.viewer.viewer as runtime
    original = runtime.make_frame
    async with contrast_view(stack) as (viewer, nav, pipe, _, task):
        old_frame = viewer.frame
        def broken(session, request):
            if session._image.plane_selection.z == 3:
                raise OSError('synthetic missing tile')
            return original(session, request)
        monkeypatch.setattr(runtime, 'make_frame', broken)
        pipe.send_text(']')
        await eventually(lambda: 'synthetic missing tile' in nav.error, task)
        await ready(viewer, task)
        assert nav.active.z_index == 2 and nav.display_position == (0, 2, 0)
        assert nav.active.image.is_open and not task.done()
        assert viewer.frame is not None and viewer.frame.shape == old_frame.shape
        nav.go_destination(4)
        await eventually(lambda: nav.display_position == (0, 4, 0), task)
        await ready(viewer, task)


async def test_histogram_series_change_discards_old_estimates(stack):
    async with contrast_view(stack) as (viewer, nav, pipe, _, task):
        pipe.send_text('H')
        await histogram_ready(viewer, task)
        first = viewer.contrast.results[0]
        nav.select_axis('series')
        nav.go_destination(1)
        await eventually(lambda: nav.active.index == 1, task)
        await eventually(lambda: viewer.contrast.results.get(0) is not None and
                         viewer.contrast.results[0] is not first, task)
        assert viewer.contrast.results[0]._values.min() == 77
        assert viewer.histogram_mode and not task.done()
        pipe.send_text('H')
        await eventually(lambda: not viewer.histogram_mode, task)
        await ready(viewer, task)


async def test_histogram_z_t_navigation_reuses_estimate_then_renders_selected_plane(stack):
    async with contrast_view(stack) as (viewer, nav, pipe, _, task):
        pipe.send_text('H')
        await histogram_ready(viewer, task)
        result, old_frame = viewer.contrast.results[0], viewer.frame
        nav.go_destination(4)
        await eventually(lambda: nav.active.z_index == 4, task)
        assert nav.display_position == (0, 4, 0)
        assert viewer.contrast.results[0] is result and viewer.frame is old_frame
        pipe.send_text('H')
        await eventually(lambda: not viewer.histogram_mode, task)
        await ready(viewer, task)
        assert nav.presented_position == (0, 4, 0) and viewer.frame is not old_frame


async def test_histogram_payload_eviction_does_not_restart_automatic_sampling(stack):
    async with contrast_view(stack, automatic=True, window=None) as (viewer, _, _, _, task):
        await eventually(lambda: len(viewer.contrast.results) == 2 and
                         viewer.contrast.job is None, task)
        await ready(viewer, task)
        first, second = viewer.contrast.results.values()
        viewer.contrast.cache_budget = max(first.nbytes, second.nbytes)
        viewer.contrast._store_result(1, second)
        assert list(viewer.contrast.results) == [1]
        assert viewer.contrast.cache_bytes <= viewer.contrast.cache_budget
        windows = tuple(viewer.windows)
        viewer.contrast.queue_automatic()
        assert not viewer.contrast.queue and viewer.contrast.completed == {0, 1}
        assert tuple(viewer.windows) == windows


async def test_rapid_plane_change_does_not_publish_obsolete_glyphs(stack, monkeypatch):
    import twhy.viewer.viewer as runtime
    original = runtime.make_frame
    entered, release = threading.Event(), threading.Event()
    async with contrast_view(stack) as (viewer, nav, pipe, _, task):
        old_frame = viewer.frame
        def delayed(session, request):
            if session._image.plane_selection.z == 3:
                entered.set()
                assert release.wait(5)
            return original(session, request)
        monkeypatch.setattr(runtime, 'make_frame', delayed)
        try:
            pipe.send_text(']')
            await eventually(entered.is_set, task)
            pipe.send_text(']')
            await eventually(lambda: nav.target_z == 4, task)
            assert viewer.frame is old_frame and nav.presented_position == (0, 2, 0)
        finally:
            release.set()
        await eventually(lambda: nav.presented_position == (0, 4, 0), task)
        await ready(viewer, task)
        assert nav._rollback is None


async def test_real_sgr_mouse_drag_and_crossing_guard(stack):
    async with contrast_view(stack) as (viewer, _, pipe, _, task):
        pipe.send_text('H')
        await histogram_ready(viewer, task)
        plot = viewer.contrast.plot
        # Wait for an actual repaint: creating content alone does not install
        # prompt_toolkit's current screen hit-test map.
        def histogram_painted():
            screen = viewer.application.renderer.last_rendered_screen
            return screen is not None and 'HISTOGRAM' in ''.join(
                screen.data_buffer[2][x].char for x in range(viewer.canvas_size[0]))
        await eventually(histogram_painted, task)
        # Two header rows precede the canvas; SGR coordinates are one-based.
        y = plot.handle_row + 3
        x = plot.upper_column + 1
        target = (plot.left + plot.right) // 2
        pipe.send_bytes((f'\x1b[<0;{x};{y}M'
                         f'\x1b[<32;{target + 1};{y}M'
                         f'\x1b[<0;{target + 1};{y}m').encode())
        await eventually(lambda: viewer.windows[0].upper < 20000, task)
        assert viewer.windows[0].upper == pytest.approx(plot.value_at(target))
        viewer.canvas.create_content(*viewer.canvas_size)
        plot = viewer.contrast.plot
        # Dragging the lower marker beyond the upper one cannot invert limits.
        mouse(viewer, MouseEventType.MOUSE_DOWN, plot.lower_column, plot.handle_row)
        mouse(viewer, MouseEventType.MOUSE_MOVE, plot.right + 100, plot.handle_row)
        mouse(viewer, MouseEventType.MOUSE_UP, plot.right + 100, plot.handle_row)
        assert viewer.windows[0].lower < viewer.windows[0].upper


async def test_quit_joins_an_inflight_contrast_read_before_closing_source(stack, monkeypatch):
    import twhy.contrast_sampling as sampling
    original = sampling.ContrastEstimator.step
    entered, release = threading.Event(), threading.Event()
    def delayed(job):
        entered.set()
        assert release.wait(5)
        assert job._source.source.is_open
        return original(job)
    monkeypatch.setattr(sampling.ContrastEstimator, 'step', delayed)
    async with contrast_view(stack) as (viewer, nav, pipe, _, task):
        dataset = nav.active.dataset
        pipe.send_text('H')
        await eventually(entered.is_set, task)
        # Release from another thread because executor shutdown correctly joins.
        def finish():
            assert dataset.is_open
            release.set()
        timer = threading.Timer(.15, finish)
        timer.start()
        try:
            pipe.send_bytes(b'\x11')
            await asyncio.wait_for(task, 5)
        finally:
            release.set()
            timer.join()
        assert not dataset.is_open
        assert viewer.contrast.job is None


async def test_manual_edit_wins_over_queued_not_yet_started_estimate(stack, monkeypatch):
    import twhy.contrast_sampling as sampling
    original = sampling.ContrastEstimator.step
    entered, release = threading.Event(), threading.Event()

    def delayed(job):
        if job._source.channel == 0 and not entered.is_set():
            entered.set()
            assert release.wait(5)
        return original(job)

    monkeypatch.setattr(sampling.ContrastEstimator, 'step', delayed)
    async with contrast_view(stack, automatic=True, window=None) as (viewer, _, pipe, _, task):
        try:
            await eventually(entered.is_set, task)
            assert viewer.contrast.queue.get(1) is True
            pipe.send_text('.u\x01\x0b19000\r')
            await eventually(lambda: viewer.windows[1].upper == 19000, task)
            assert viewer.contrast.queue.get(1) is False
        finally:
            release.set()
        await eventually(lambda: 1 in viewer.contrast.results, task)
        assert viewer.windows[1].upper == 19000


async def test_pending_series_change_cancels_old_channel_numeric_entry(stack, monkeypatch):
    async with contrast_view(stack) as (viewer, nav, pipe, _, task):
        original = nav.document.load
        entered, release = threading.Event(), threading.Event()

        def delayed(index):
            if index == 1:
                entered.set()
                assert release.wait(5)
            return original(index)

        monkeypatch.setattr(nav.document, 'load', delayed)
        nav.select_axis('series')
        nav.go_destination(1)
        try:
            await eventually(entered.is_set, task)
            pipe.send_text('.u')
            await eventually(lambda: viewer.editing == 'upper' and viewer.focused_channel == 1,
                             task)
        finally:
            release.set()
        await eventually(lambda: nav.active.index == 1, task)
        await ready(viewer, task)
        assert viewer.editing is None and len(viewer.windows) == 1
        assert viewer.windows[0] == IntensityWindow(0, 20000)
