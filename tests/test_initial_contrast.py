"""Startup contrast is decided before presentation, never applied behind the user."""
from __future__ import annotations

import asyncio

import pytest
import tifffile
import numpy as np

from twhy import ContrastConfig, estimate_contrast
from test_contrast_viewer import contrast_view, FAST, histogram_ready
from test_viewer import eventually, ready
from test_zt_navigation import write_stack


def test_fast_startup_config_keeps_sampling_statistics_and_caps_work():
    from twhy.viewer.initial_contrast import initial_contrast_config

    original = ContrastConfig(seed=31, highlight_quantile=.93, bootstrap_replicates=80)
    quick = initial_contrast_config(original)
    assert quick.seed == 31 and quick.highlight_quantile == .93
    assert quick.bootstrap_replicates == 0
    assert quick.draws == 24 and quick.survey_reads == 12
    assert quick.max_base_samples == 24_576 and quick.survey_samples == 24_576
    assert original.bootstrap_replicates == 80  # Never mutate the library configuration.


def test_interactive_default_is_less_tail_conservative_than_library_default():
    from twhy.viewer.contrast import ContrastController

    class Dummy:
        pass

    assert ContrastConfig().highlight_quantile == .995
    assert ContrastController(Dummy()).config.highlight_quantile == .90


@pytest.mark.parametrize('axes', ['CYX', 'TCZYX'])
async def test_real_ome_tiff_first_frame_has_fixed_source_informed_windows(tmp_path, axes):
    path = tmp_path / f'{axes}.ome.tif'
    write_stack(path, axes=axes)
    async with contrast_view(path, automatic=True, window=None) as (viewer, nav, pipe, _, task):
        assert nav.document.kind == 'tiff'
        assert len(viewer.contrast.startup_results) == 2
        assert not viewer.contrast.results  # Full histogram is a deliberate H/A operation.
        first = tuple(viewer.windows)
        for channel, result in viewer.contrast.startup_results.items():
            assert result.window == first[channel]
            assert result.survey_reads <= 8 and result.base_reads <= 24
        frame, generation = viewer.frame, viewer.generation
        await asyncio.sleep(.15)
        assert viewer.frame is frame and viewer.generation == generation
        assert tuple(viewer.windows) == first
        assert not viewer.contrast.queue and viewer.contrast.job is None
        pipe.send_text('H')
        await histogram_ready(viewer, task)
        # The complete histogram can refine the estimated distribution without
        # changing the limits or retroactively re-lighting the displayed image.
        await eventually(lambda: 0 in viewer.contrast.results, task)
        assert tuple(viewer.windows) == first
        pipe.send_text('H')
        await eventually(lambda: not viewer.histogram_mode, task)
        await ready(viewer, task)
        assert tuple(viewer.windows) == first


async def test_startup_budget_exhaustion_freezes_preview_and_never_relights(
        tmp_path, monkeypatch):
    import twhy.viewer.viewer as runtime

    monkeypatch.setattr(runtime, 'STARTUP_CONTRAST_SECONDS', 0.)
    path = tmp_path / 'slow.ome.tif'
    write_stack(path)
    async with contrast_view(path, automatic=True, window=None) as (viewer, _, pipe, _, task):
        assert not viewer.contrast.startup_results
        first = tuple(viewer.windows)
        frame, generation = viewer.frame, viewer.generation
        await asyncio.sleep(.12)
        assert tuple(viewer.windows) == first and viewer.frame is frame
        assert viewer.generation == generation and not viewer.contrast.queue
        pipe.send_text('H')
        await eventually(lambda: 0 in viewer.contrast.results, task)
        assert tuple(viewer.windows) == first


async def test_no_stack_contrast_preserves_original_preview_only_startup(tmp_path):
    path = tmp_path / 'disabled.ome.tif'
    write_stack(path, axes='CYX')
    async with contrast_view(path, automatic=False, window=None) as (viewer, _, _, _, _):
        assert not viewer.contrast.startup_results
        assert not viewer.contrast.results
        assert all(window is not None for window in viewer.windows[:2])


def test_full_library_estimator_not_affected_by_startup_policy():
    from omeify import MultichannelImage

    pixels = (np.arange(1024, dtype=np.uint16).reshape(32, 32) * 5)
    with MultichannelImage.from_array(pixels, axes='YX') as image:
        result = estimate_contrast(image, config=ContrastConfig())
    assert result.exact and result.config.highlight_quantile == .995
    assert result.window is not None

async def test_2d_mif_native_pixels_correct_coarse_preview_saturation(tmp_path):
    """Averaged pyramid pixels can underestimate the raw intensity ceiling."""
    path = tmp_path / 'many-markers.ome.tif'
    rng = np.random.default_rng(4)
    image = rng.integers(120, 800, (2, 512, 512), dtype=np.uint16)
    image[0, 100:132, 202:234] = 43000
    image[1, 270:302, 150:182] = 28000
    coarse = image.reshape(2, 128, 4, 128, 4).mean(axis=(2, 4)).round().astype(np.uint16)
    with tifffile.TiffWriter(path, ome=True) as writer:
        writer.write(image, metadata={'axes': 'CYX', 'PhysicalSizeX': .5,
                                      'PhysicalSizeY': .5},
                     photometric='minisblack', tile=(128, 128), subifds=1)
        writer.write(coarse, photometric='minisblack', tile=(128, 128), subfiletype=1)
    async with contrast_view(path, automatic=True, window=None) as (viewer, _, _, _, _):
        assert len(viewer.contrast.startup_results) == 2
        # The coarse mean pyramid has a narrow baseline (roughly 345..620).
        # The initial displayed range samples the actual base pixels instead.
        assert all(viewer.windows[c].upper > 750 for c in (0, 1))
        assert all(viewer.windows[c].lower < 200 for c in (0, 1))
        assert not viewer.contrast.results  # No second background window swap.


async def test_real_zarr_stack_startup_has_no_late_automatic_relighting(tmp_path):
    """Required backend regression; must run with the normal Zarr install."""
    from zt_zarr_fixture import write_zarr_stack

    path = tmp_path / 'rapid-planes.zarr'
    write_zarr_stack(path)
    async with contrast_view(path, automatic=True, window=None) as (viewer, _, pipe, _, task):
        window = tuple(viewer.windows)
        frame = viewer.frame
        assert all(w is not None for w in window[:2])
        assert not viewer.contrast.queue and not viewer.contrast.job
        await asyncio.sleep(.15)
        assert viewer.frame is frame and tuple(viewer.windows) == window
        pipe.send_text('H')
        await eventually(lambda: 0 in viewer.contrast.results, task)
        assert tuple(viewer.windows) == window


def test_default_viewer_bright_tail_policy_boosts_midtones_without_changing_cdf():
    """The more protected library tail can visually compress a broad intensity field."""
    from omeify import MultichannelImage

    rng = np.random.default_rng(10)
    pixels = rng.exponential(2500, (512, 512)).clip(0, 50000).astype(np.uint16)
    pixels.ravel()[::1000] = 45000
    from twhy.viewer.initial_contrast import initial_contrast_config

    library = initial_contrast_config(ContrastConfig(bootstrap_replicates=0))
    viewer = initial_contrast_config(ContrastConfig(
        highlight_quantile=.90, bootstrap_replicates=0))
    with MultichannelImage.from_array(pixels, axes='YX') as source:
        from twhy import estimate_contrast
        high = estimate_contrast(source, config=library)
        bright = estimate_contrast(source, config=viewer)
    assert high.window.upper > bright.window.upper
    assert bright.window.upper > bright.window.lower
    np.testing.assert_array_equal(high._values, bright._values)
    np.testing.assert_array_equal(high._weights, bright._weights)


async def test_slow_startup_sampling_cannot_apply_after_first_frame(tmp_path, monkeypatch):
    import time
    import twhy.contrast_sampling as sampling
    import twhy.viewer.viewer as runtime

    original = sampling.ContrastEstimator.step

    def deliberately_slow(job):
        time.sleep(.04)
        return original(job)

    monkeypatch.setattr(sampling.ContrastEstimator, 'step', deliberately_slow)
    monkeypatch.setattr(runtime, 'STARTUP_CONTRAST_SECONDS', .01)
    path = tmp_path / 'slow-but-valid.ome.tif'
    write_stack(path)
    async with contrast_view(path, automatic=True, window=None) as (viewer, _, _, _, _):
        assert not viewer.contrast.startup_results
        first, frame = tuple(viewer.windows), viewer.frame
        await asyncio.sleep(.15)
        assert tuple(viewer.windows) == first and viewer.frame is frame
        assert not viewer.contrast.job and not viewer.contrast.queue
