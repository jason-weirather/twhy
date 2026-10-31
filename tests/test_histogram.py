import numpy as np
import pytest

from omeify import MultichannelImage
from twhy import IntensityWindow, estimate_contrast, render_histogram


@pytest.fixture
def estimate():
    values = (np.arange(4096).reshape(64, 64) % 200).astype(np.uint16)
    with MultichannelImage.from_array(values, axes='YX', channel_names=('DNA',)) as image:
        return estimate_contrast(image)


@pytest.mark.parametrize('columns,rows', [(100, 30), (60, 18), (24, 12), (15, 6)])
def test_histogram_dimensions_and_pure_ascii(estimate, columns, rows):
    view = render_histogram(estimate, columns=columns, rows=rows, ascii_only=True)
    assert view.frame.shape == (rows, columns)
    assert view.frame.to_text().isascii()
    assert all(len(line) == columns for line in view.frame.to_text().splitlines())
    assert view.frame.foreground is None


def test_handles_match_raw_intensity_coordinates(estimate):
    window = IntensityWindow(30, 140)
    view = render_histogram(estimate, window=window, columns=100, rows=25,
                            color=(0., 1., 1.))
    assert view.frame.characters[view.handle_row, view.lower_column] == '^'
    assert view.frame.characters[view.handle_row, view.upper_column] == '^'
    delta = (view.maximum - view.minimum) / (view.right - view.left)
    assert abs(view.value_at(view.lower_column) - 30) <= delta
    assert abs(view.value_at(view.upper_column) - 140) <= delta
    assert view.value_at(-100) == view.minimum and view.value_at(1000) == view.maximum
    assert 'exact census' in view.frame.to_text()
    assert view.frame.foreground is not None


def test_log_scale_never_changes_histogram_or_window(estimate):
    original = estimate.probability.copy()
    a = render_histogram(estimate, log_counts=True)
    b = render_histogram(estimate, log_counts=False)
    assert a.minimum == b.minimum and a.maximum == b.maximum
    assert a.lower_column == b.lower_column and a.upper_column == b.upper_column
    np.testing.assert_array_equal(original, estimate.probability)


def test_coincident_carets_small_and_hostile_metadata():
    with MultichannelImage.from_array(np.zeros((8, 8), np.uint16), axes='YX',
                                      channel_names=('DNA\t\x1b[31m漢',)) as image:
        result = estimate_contrast(image)
    view = render_histogram(result, columns=50, rows=16)
    assert '\x1b' not in view.frame.to_text()
    assert '\t' not in view.frame.to_text()
