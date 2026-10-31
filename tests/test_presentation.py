"""Quiet activity chrome and histogram styling preserve image/data contracts."""
from __future__ import annotations

import asyncio
from dataclasses import replace
import threading
from types import SimpleNamespace

import numpy as np
import pytest
from prompt_toolkit.mouse_events import MouseEventType

from omeify import MultichannelImage
from twhy import IntensityWindow, estimate_contrast, render_histogram
from twhy.viewer.activity import ACTIVITY_INTERVAL, ACTIVITY_WIDTH, activity_fragments
from test_contrast_viewer import contrast_view, histogram_ready, mouse
from test_viewer import eventually, ready
from test_zt_navigation import write_stack


@pytest.fixture
def stack(tmp_path):
    path = tmp_path / 'presentation.ome.tif'
    write_stack(path, extra_series=True)
    return path


@pytest.fixture
def estimate():
    # Empty bins and a sharp second mode must survive the styling pass.
    values = np.concatenate((np.arange(800) % 41, np.full(100, 140),
                             np.full(100, 199))).astype(np.uint16).reshape(25, 40)
    with MultichannelImage.from_array(values, axes='YX', channel_names=('Signal',)) as image:
        return estimate_contrast(image)


def fragments_text(fragments):
    return ''.join(part[1] for part in fragments)


def test_pulse_has_fixed_ascii_width_and_time_based_phase():
    view = SimpleNamespace(activity_pending=True)
    phases = []
    for index in range(8):
        text = fragments_text(activity_fragments(view, now=index * ACTIVITY_INTERVAL))
        assert len(text) == ACTIVITY_WIDTH == 5 and text.isascii()
        assert text.count('o') == 1 and text.count('.') == 2
        phases.append(text)
    assert phases[:4] == [' o.. ', ' .o. ', ' ..o ', ' .o. ']
    assert phases[:4] == phases[4:]
    view.activity_pending = False
    assert fragments_text(activity_fragments(view, now=100)) == ' ' * ACTIVITY_WIDTH


@pytest.mark.parametrize('fullscreen', [False, True])
async def test_delayed_plane_uses_only_corner_pulse_and_keeps_grid_labels(stack, monkeypatch,
                                                                      fullscreen):
    import twhy.viewer.viewer as runtime
    original = runtime.make_frame
    entered, release = threading.Event(), threading.Event()
    calls = []
    async with contrast_view(stack) as (viewer, nav, pipe, output, task):
        if fullscreen:
            viewer.toggle_fullscreen()
            await ready(viewer, task)
        old_frame, old_lines = viewer.frame, viewer.cell_lines
        old_message, old_title, old_status = viewer.message, viewer._title(), viewer._status()
        old_size = viewer.canvas_size

        def delayed(session, request):
            calls.append(request)
            if session._image.plane_selection.z == 3:
                entered.set()
                assert release.wait(5)
            return original(session, request)

        monkeypatch.setattr(runtime, 'make_frame', delayed)
        try:
            pipe.send_text(']')
            await eventually(entered.is_set, task)
            assert viewer.activity_pending
            reads = nav.active.dataset.cache_info()['loads']
            await asyncio.sleep(.35)
            assert len(calls) == 1  # Timer repaint must not submit a render.
            assert nav.active.dataset.cache_info()['loads'] == reads
            assert viewer.frame is old_frame and viewer.cell_lines is old_lines
            assert viewer.canvas_size == old_size and viewer._title() == old_title
            assert nav.display_position == (0, 2, 0)
            assert viewer.message == old_message and viewer._status() == old_status
            assert not any(word in nav.status(compact=True).lower()
                           for word in ('opening', 'showing', 'rendering', 'updating'))
            screen = viewer.application.renderer.last_rendered_screen
            corner = ''.join(screen.data_buffer[0][x].char
                             for x in range(output.size.columns - 5, output.size.columns))
            assert corner in (' o.. ', ' .o. ', ' ..o ')
        finally:
            release.set()
        await eventually(lambda: nav.display_position == (0, 3, 0), task)
        await ready(viewer, task)
        assert not viewer.activity_pending and nav._rollback is None
        assert viewer.message == old_message
        assert viewer.frame is not old_frame
        # There is no permanent fullscreen overlay, and normal chrome reserves
        # the same five cells after completion rather than shifting the title.
        await asyncio.sleep(.15)
        screen = viewer.application.renderer.last_rendered_screen
        corner = ''.join(screen.data_buffer[0][x].char
                         for x in range(output.size.columns - 5, output.size.columns))
        assert 'o' not in corner and '.' not in corner
        if not fullscreen:
            assert corner == ' ' * 5


async def test_slow_source_open_is_quiet_and_error_is_still_visible(stack, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    async with contrast_view(stack) as (viewer, nav, pipe, _, task):
        old_message, old_title, old_frame = viewer.message, viewer._title(), viewer.frame
        original = nav.document.load_plane
        def broken(index, *, z_index, t_index):
            if z_index == 3:
                entered.set()
                assert release.wait(5)
                raise OSError('deliberately unreadable plane')
            return original(index, z_index=z_index, t_index=t_index)
        monkeypatch.setattr(nav.document, 'load_plane', broken)
        try:
            pipe.send_text(']')
            await eventually(entered.is_set, task)
            assert nav.loading and viewer.activity_pending
            assert nav.status(compact=True) == ''
            assert viewer.frame is old_frame and viewer._title() == old_title
            assert viewer.message == old_message
        finally:
            release.set()
        await eventually(lambda: 'unreadable plane' in nav.error, task)
        await ready(viewer, task)
        assert not viewer.activity_pending
        assert 'unreadable plane' in nav.status(compact=True)
        assert 'unreadable plane' in viewer.message
        assert nav.display_position == (0, 2, 0)


async def test_idle_pulse_does_not_repaint_forever(stack, monkeypatch):
    async with contrast_view(stack) as (viewer, _, _, _, _):
        await asyncio.sleep(.3)
        calls = []
        original = viewer.application.invalidate
        def tracked():
            calls.append(True)
            original()
        monkeypatch.setattr(viewer.application, 'invalidate', tracked)
        assert not viewer.activity_pending
        await asyncio.sleep(.4)
        assert not calls


@pytest.mark.parametrize('size', [(120, 36), (100, 30), (60, 24), (40, 18), (24, 12)])
@pytest.mark.parametrize('ascii_only', [False, True])
@pytest.mark.parametrize('colored', [False, True])
def test_histogram_geometry_controls_and_immutable_statistics(estimate, size, ascii_only, colored):
    columns, rows = size
    window = IntensityWindow(20, 145)
    before = tuple(getattr(estimate, name).tobytes() for name in
                   ('bin_edges', 'probability', '_values', '_weights'))
    view = render_histogram(estimate, window=window, columns=columns, rows=rows,
                            ascii_only=ascii_only, color=(.3, .6, 1.) if colored else None)
    assert view.frame.shape == (rows, columns)
    assert 0 <= view.left <= view.lower_column <= view.upper_column <= view.right < columns
    assert view.frame.characters[view.handle_row, view.lower_column] == ('^' if ascii_only else '▲')
    assert view.frame.characters[view.handle_row, view.upper_column] == ('^' if ascii_only else '▲')
    assert view.value_at(view.left) == view.minimum and view.value_at(view.right) == view.maximum
    assert (view.frame.foreground is None) is not colored
    assert (view.frame.background is None) is not colored
    text = view.frame.to_text()
    assert all(len(row) == columns for row in text.splitlines())
    if ascii_only:
        assert text.isascii()
    after = tuple(getattr(estimate, name).tobytes() for name in
                  ('bin_edges', 'probability', '_values', '_weights'))
    assert before == after and estimate.window != window


@pytest.mark.parametrize('log_counts', [False, True])
def test_skyline_is_unsmoothed_bin_height_including_clipped_tail(estimate, log_counts):
    view = render_histogram(estimate, window=IntensityWindow(30, 80), columns=100, rows=30,
                            log_counts=log_counts, color=(.2, .7, 1.))
    width = view.right - view.left + 1
    _, probability = estimate.histogram(width, value_range=(view.minimum, view.maximum))
    counts = probability * estimate.population_samples * estimate.finite_fraction
    weights = np.log1p(counts) if log_counts else counts
    baseline, top = view.handle_row - 2, 3
    expected = weights / weights.max() * (baseline - top)
    glyphs = ' ▁▂▃▄▅▆▇█'
    measured = []
    for column in range(view.left, view.right + 1):
        measured.append(sum(glyphs.index(ch) / 8 for ch in
                            view.frame.characters[top:baseline, column] if ch in glyphs))
    np.testing.assert_allclose(measured, np.ceil(expected * 8) / 8, atol=1e-12)
    assert np.count_nonzero(probability == 0) > 20
    assert any(measured[x] > 0 for x in range(view.upper_column - view.left + 1, width))


def test_coincident_handles_are_marked_and_ascii_fallback_is_explicit(estimate):
    view = render_histogram(estimate, window=IntensityWindow(50, 50.000001), columns=60, rows=24)
    assert view.lower_column == view.upper_column
    assert view.frame.characters[view.handle_row, view.lower_column] == '◆'
    assert 'L 50' in view.frame.to_text() and 'U 50' in view.frame.to_text()
    other = render_histogram(estimate, window=IntensityWindow(50, 50.000001),
                             columns=60, rows=24, ascii_only=True)
    assert other.frame.characters[other.handle_row, other.lower_column] == '^'


async def test_coincident_upper_handle_can_be_dragged_from_its_right_side(stack):
    async with contrast_view(stack) as (viewer, _, pipe, _, task):
        pipe.send_text('H')
        await histogram_ready(viewer, task)
        result = viewer.contrast.results[0]
        value = float(result._values.mean())
        viewer.windows[0] = IntensityWindow(value, value + .00001)
        viewer.canvas.create_content(*viewer.canvas_size)
        plot = viewer.contrast.plot
        assert plot.lower_column == plot.upper_column
        mouse(viewer, MouseEventType.MOUSE_DOWN, plot.upper_column + 1, plot.handle_row)
        assert viewer.contrast.drag[1] == 'upper'
        mouse(viewer, MouseEventType.MOUSE_UP, plot.upper_column + 3, plot.handle_row)
        assert viewer.windows[0].lower == value
        assert viewer.windows[0].upper > value + .00001


@pytest.mark.parametrize('color', [(1., 2., 0.), (1., 2.), (1., float('nan'), 0.)])
@pytest.mark.parametrize('columns,rows', [(100, 30), (8, 4)])
def test_invalid_color_fails_consistently_even_in_small_canvas(estimate, color, columns, rows):
    with pytest.raises(ValueError, match='color'):
        render_histogram(estimate, color=color, columns=columns, rows=rows)


def test_warning_and_suggested_interval_not_confused_with_current_limits(estimate):
    result = replace(estimate, exact=False, upper_interval=(170., 180.),
                     warnings=('pilot_coverage_is_partial', 'upper_tail_supported_by_few_tiles'))
    view = render_histogram(result, window=IntensityWindow(10, 50), columns=100, rows=28)
    text = view.frame.to_text()
    assert 'Suggested U ~95% [170, 180]' in text
    assert 'U 50' in text and 'upper tail supported by few tiles' in text
    assert 'exact census' not in text
