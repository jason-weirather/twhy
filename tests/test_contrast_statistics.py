"""Independent finite-population oracles for the reusable estimator/statistics."""
import json

import numpy as np
import pytest

from omeify import ImageDataset, MultichannelImage, RGBImage, LabelImage
from twhy import ContrastConfig, ContrastEstimator, estimate_contrast
from twhy.contrast import weighted_quantile
from twhy.contrast_sampling import _Grid
from twhy.contrast_statistics import summarize_draws


def test_weighted_quantile_does_not_count_bright_oversampling_as_population():
    assert weighted_quantile([0, 100, 100], [.99, .005, .005], .98) == 0
    assert weighted_quantile([0, 100, 100], [.99, .005, .005], .995) == 100
    assert weighted_quantile([0, 10, 20], [0, 1, 0], 0) == 10
    assert weighted_quantile([0, 10, 20], [0, 1, 0], 1) == 10
    assert weighted_quantile([0, 10, 20], [1e308, 1e308, 1e308], .5) == 10


@pytest.mark.parametrize('values,weights', [([], []), ([1], [0]), ([np.nan], [1]),
                                           ([1], [-1]), ([[1]], [[1]])])
def test_invalid_weighted_inputs_fail(values, weights):
    with pytest.raises(ValueError):
        weighted_quantile(values, weights, .5)


@pytest.mark.parametrize('options', [{'draws': 0}, {'seed': True}, {'uniform_fraction': 0},
                                    {'lower_quantile': .999}, {'upper_policy': 'unknown'},
                                    {'histogram_bins': 1}, {'survey_reads': -1}])
def test_config_validation(options):
    with pytest.raises((ValueError, TypeError)):
        ContrastConfig(**options)


def test_small_complete_stack_census_and_owned_json_report():
    data = np.arange(3 * 2 * 5 * 7, dtype=np.uint16).reshape(3, 2, 5, 7)
    with ImageDataset.from_array(data, axes='TZYX') as source:
        r = estimate_contrast(source, config=ContrastConfig(upper_policy='percentile'))
        assert r.exact and r.population_samples == data.size
        assert r.unique_sampled_samples == data.size and r.base_planes == 6
        for limit in [0, 11, 69, 200, 300]:
            assert r.cdf(limit) == pytest.approx(np.mean(data <= limit))
        assert r.window.lower == np.sort(data.ravel())[int(np.ceil(.01 * data.size)) - 1]
        assert r.window.upper == np.sort(data.ravel())[int(np.ceil(.995 * data.size)) - 1]
        assert source.is_open
    assert r.probability.sum() == pytest.approx(1)
    json.dumps(r.to_dict(), allow_nan=False)
    with pytest.raises(ValueError):
        r.probability[0] = 1
    assert r.histogram(11)[1].sum() == pytest.approx(1)


def test_rare_clean_signal_survives_without_biasing_histogram():
    data = np.zeros((128, 128), dtype=np.uint16)
    data[51, 27:29] = 60000
    with MultichannelImage.from_array(data, axes='YX') as image:
        r = estimate_contrast(image)
        ordinary = estimate_contrast(image, config=ContrastConfig(upper_policy='percentile'))
    assert r.exact and r.window.upper == 60000
    assert r.cdf(0) == pytest.approx(1 - 2 / data.size)
    assert r.clipped_fraction(1) == pytest.approx(2 / data.size)
    # The all-background percentile collapses; its documented range fallback also
    # protects this exact all-zero-background case. The new rule matters when the
    # lower tail has width, as checked below.
    assert ordinary.window.upper == 60000


def test_noise_width_does_not_hide_a_rare_bright_tail():
    data = np.arange(128 * 128, dtype=np.uint16).reshape(128, 128) % 10
    data[51, 27:29] = 60000
    with MultichannelImage.from_array(data, axes='YX') as image:
        guided = estimate_contrast(image)
        percentile = estimate_contrast(image, config=ContrastConfig(upper_policy='percentile'))
    assert percentile.window.upper == 9
    assert guided.window.upper == 60000
    np.testing.assert_array_equal(guided._values, percentile._values)
    np.testing.assert_array_equal(guided._weights, percentile._weights)


@pytest.mark.parametrize('value', [0., 12., -12.])
def test_constants_have_valid_windows(value):
    with MultichannelImage.from_array(np.full((8, 9), value), axes='YX') as image:
        r = estimate_contrast(image)
    assert r.window.lower < r.window.upper
    assert 'constant_sample' in r.warnings


def test_nonfinite_population_separate_from_real_zero():
    a = np.array([[np.nan, np.inf, -np.inf], [0, 10, 30]], dtype=float)
    with MultichannelImage.from_array(a, axes='YX') as image:
        r = estimate_contrast(image)
    assert r.finite_fraction == .5 and r.cdf(0) == pytest.approx(1 / 3)
    assert r.window.upper == 30
    with MultichannelImage.from_array(a[:1], axes='YX') as image:
        r = estimate_contrast(image)
    assert r.window is None and not r.probability.any()
    json.dumps(r.to_dict(), allow_nan=False)


def test_rgb_range_and_categorical_boundary():
    data = np.full((7, 9, 3), 80, np.uint8)
    with RGBImage.from_array(data) as image:
        r = estimate_contrast(image)
        assert image.is_open
    assert r.window.lower == 0 and r.window.upper == 255
    assert r.policy == 'rgb-native' and r.population_samples == data.size
    with LabelImage.from_array(np.ones((8, 9), np.uint16)) as image:
        with pytest.raises(ValueError, match='Categorical'):
            estimate_contrast(image)


def test_defensive_proposal_normalization_edges_and_hh_totals():
    grid = _Grid((2, 3, 35, 37), 16)
    grid.scores[:] = np.arange(grid.scores.size)
    grid.freeze()
    alpha, qs, target, hh_total = .5, [], [], 0.
    # Enumerate every tile, including all unequal edge sizes. Its exact proposal
    # probability must integrate to one; inverse-weighted totals recover the target.
    for t in range(2):
        for z in range(3):
            for iy in range(3):
                for ix in range(3):
                    y0, y1, x0, x1 = grid.bounds(iy, ix)
                    area = (y1 - y0) * (x1 - x0)
                    group = int(grid.groups((t, z, y0, x0)))
                    q = area * (alpha / grid.population +
                                (1 - alpha) * grid.proposal[group] / grid.volumes[group])
                    p = area / grid.population
                    qs.append(q)
                    target.append(p)
                    assert q > 0 and p / q <= 1 / alpha + 1e-12
                    # Indicator of t=1 is a known finite-population functional.
                    hh_total += q * (p / q) * int(t == 1)
    assert sum(qs) == pytest.approx(1) and sum(target) == pytest.approx(1)
    assert hh_total == pytest.approx(.5)


def test_bootstrap_resamples_draws_not_correlated_pixels():
    # Each tile is perfectly constant. Replicating its pixels must not narrow
    # the interval as though those correlated observations were new draws.
    cfg = ContrastConfig(upper_quantile=.6, upper_policy='percentile', bootstrap_replicates=80)
    values = [np.full(4, i) for i in range(32)]
    a = summarize_draws(values, np.ones(32), list(range(32)), config=cfg, exact=False)
    b = summarize_draws([np.repeat(v, 100) for v in values], np.ones(32), list(range(32)),
                        config=cfg, exact=False)
    assert a['upper_interval'] is not None
    assert a['upper_interval'] == b['upper_interval']
    assert a['lower_interval'] == b['lower_interval']
    assert a['draw_weight_ess'] == b['draw_weight_ess'] == 32


def test_no_fake_precision_for_single_bright_tile():
    cfg = ContrastConfig()
    arrays = [np.zeros(32) for _ in range(31)] + [np.full(32, 400.)]
    r = summarize_draws(arrays, np.ones(32), list(range(32)), config=cfg, exact=False)
    assert r['window'].upper == 400
    assert r['upper_interval'] is None and r['upper_support_tiles'] == 1
    assert any('upper_tail' in warning for warning in r['warnings'])


def test_reproducible_fixed_budget_no_mutation_or_extra_reads():
    data = np.random.default_rng(2).integers(0, 1000, size=(4, 7, 101, 103), dtype=np.uint16)
    original = data.copy()
    cfg = ContrastConfig(seed=19, draws=20, max_base_samples=5000,
                         survey_reads=5, survey_samples=2000, bootstrap_replicates=0)
    with ImageDataset.from_array(data, axes='TZYX') as source:
        a, b = estimate_contrast(source, config=cfg), estimate_contrast(source, config=cfg)
        assert source.is_open
    np.testing.assert_array_equal(data, original)
    np.testing.assert_array_equal(a._values, b._values)
    np.testing.assert_array_equal(a._weights, b._weights)
    assert a.window == b.window and not a.exact
    assert a.sampled_samples <= 5000 and a.survey_samples <= 2000 and a.survey_reads <= 5
    assert a.base_planes > 1 and a.base_reads <= 20


def test_cancel_and_stale_image_lifetime():
    image = MultichannelImage.from_array(np.arange(4096).reshape(64, 64).astype(np.uint16),
                                         axes='YX').open()
    try:
        job = ContrastEstimator(image, config=ContrastConfig(draws=2))
        job.step()
        job.cancel()
        assert job.done and job.result is None and not job.step()
        assert image.is_open
        old = ContrastEstimator(image)
        image.close()
        image.open()
        with pytest.raises(RuntimeError):
            old.step()
        old.close()
    finally:
        image.close()


def test_channel_and_budget_errors():
    with ImageDataset.from_array(np.ones((2, 5, 6), np.uint16), axes='CYX') as source:
        with pytest.raises(IndexError):
            estimate_contrast(source, channel=2)
        with pytest.raises(TypeError):
            estimate_contrast(source, channel=True)
        result = estimate_contrast(source, channel=1,
                                   config=ContrastConfig(max_base_samples=3, survey_reads=0))
        assert result.sampled_samples <= 3


def test_public_estimator_import_does_not_import_omeify_or_terminal():
    import os
    import subprocess
    import sys
    script = '''
import builtins
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name.split('.')[0] in {'omeify', 'prompt_toolkit', 'pypdfium2'}:
        raise AssertionError('unexpected import: ' + name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from twhy import ContrastConfig, ContrastEstimator, estimate_contrast, render_histogram
assert ContrastConfig().uniform_fraction == .5
'''
    run = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True,
                         env=os.environ.copy(), timeout=10)
    assert run.returncode == 0, run.stderr


def test_config_normalizes_numpy_numbers_for_json():
    import json
    from dataclasses import asdict
    config = ContrastConfig(seed=np.int64(7), uniform_fraction=np.float32(.5))
    json.dumps(asdict(config), allow_nan=False)
    with pytest.raises(TypeError):
        ContrastConfig(uniform_fraction=True)
