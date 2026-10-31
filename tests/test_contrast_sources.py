"""Real regional providers and backend integrations for pyramid-guided sampling."""
from dataclasses import replace

import numpy as np
import pytest

from omeify import AxisInfo, DatasetLevel, ImageDataset, ImageMetadata, PixelSize, open_dataset
from omeify.io.dataset_source import DatasetSourceBase
from twhy import ContrastConfig, ContrastEstimator, estimate_contrast
from test_zt_navigation import write_stack


class GuidePyramid(DatasetSourceBase):
    """Independent base/XY/XYZ fixture. Deliberately exaggerated guide intensities."""

    def __init__(self, *, xyz=False, mapped=True):
        super().__init__()
        rng = np.random.default_rng(5)
        base = rng.integers(1, 100, (3, 2, 4, 64, 64), dtype=np.uint16)
        base[2, :, 2, 16:32, 32:48] += 2000
        dz = 2 if xyz else 1
        coarse = base[:, :, ::dz, ::4, ::4].astype(np.float32) * 10
        self.arrays = (base, coarse.astype(base.dtype))
        self.reads = []
        descriptors = []
        for level, array in enumerate(self.arrays):
            axes = []
            for name, size in zip('TCZYX', array.shape, strict=True):
                kind = 'time' if name == 'T' else 'channel' if name == 'C' else 'space'
                scale = (2 if name == 'Z' else 4 if name in 'YX' else 1) if level else 1
                scale = 1 if name == 'Z' and not xyz else scale
                axes.append(AxisInfo(name, size, kind,
                                     unit='s' if name == 'T' else 'µm' if kind == 'space' else None,
                                     scale=scale if name != 'C' else None,
                                     origin=0. if mapped and name != 'C' else None))
            metadata = ImageMetadata('CYX', (2, *array.shape[-2:]), base.dtype,
                                     channel_names=('A', 'B'), pixel_size=PixelSize(1, 1, 'µm'))
            descriptors.append(DatasetLevel(level, tuple(axes), metadata, not xyz or not level))
        self.descriptors = tuple(descriptors)
        self.plane_level_indices = (0,)

    @property
    def dataset_levels(self):
        self._ensure_open()
        return self.descriptors

    def plane_metadata(self, *, z=None, t=None, level=0):
        return self.descriptors[level].plane_metadata

    def read_plane_region(self, y0, y1, x0, x1, *, z, t, level, channels, speculative=False):
        self.reads.append((t, z, level, (y0, y1, x0, x1), channels))
        return np.stack([self.arrays[level][t, c, z, y0:y1, x0:x1] for c in channels])


@pytest.mark.parametrize('xyz', [False, True])
def test_coarse_guide_never_becomes_histogram_or_full_resolution_samples(xyz):
    source = GuidePyramid(xyz=xyz)
    cfg = ContrastConfig(draws=30, tile_size=8, bootstrap_replicates=0)
    with ImageDataset(source) as dataset:
        job = ContrastEstimator(dataset, config=cfg)
        while not job.done:
            before = len(source.reads)
            job.step()
            assert len(source.reads) - before <= 1
        result = job.result
        assert result.survey_level == 1
        assert result.survey_planes == 3 * (2 if xyz else 4)
        assert result.survey_samples == result.survey_total_samples
        assert result.survey_reads + result.base_reads == len(source.reads)
        expected_values = []
        for t, z, level, (y0, y1, x0, x1), channels in source.reads:
            if level == 0:
                expected_values.extend(source.arrays[0][t, channels[0], z, y0:y1, x0:x1].ravel())
        np.testing.assert_array_equal(result._values, np.sort(expected_values))
        assert result._values.max() <= source.arrays[0].max()
        assert result._values.max() < source.arrays[1].max()
        assert dataset.is_open


def test_unknown_geometry_keeps_uniform_defensive_support_and_reports_limit():
    with ImageDataset(GuidePyramid(mapped=False)) as dataset:
        result = estimate_contrast(dataset, config=ContrastConfig(
            draws=20, tile_size=8, survey_reads=2, survey_samples=8192, bootstrap_replicates=0))
    assert result.survey_level == 0
    assert 'unmapped_pyramid_levels_not_used_for_guidance' in result.warnings
    assert 'pilot_coverage_is_partial' in result.warnings
    assert result.sampled_samples <= 20 * 64


def test_real_tiff_estimator_matches_same_array_population(tmp_path):
    path = tmp_path / 'source.ome.tif'
    pixels = write_stack(path)
    # Census is exact and is independent of the histogram/pyramid rendering path.
    cfg = ContrastConfig(draws=1000, max_base_samples=100_000, bootstrap_replicates=0)
    with open_dataset(path, input_type='ome_tiff') as dataset:
        actual = estimate_contrast(dataset, channel=1, config=cfg)
        assert dataset.is_open
    with ImageDataset.from_array(pixels, axes='TCZYX') as dataset:
        expected = estimate_contrast(dataset, channel=1, config=cfg)
    assert actual.exact and expected.exact
    np.testing.assert_array_equal(actual._values, expected._values)
    assert actual.window == expected.window
    assert actual.population_samples == pixels[:, 1].size


def test_estimator_error_does_not_close_source_or_return_partial_result():
    source = GuidePyramid()
    with ImageDataset(source) as dataset:
        original = source.read_plane_region
        def broken(*args, **kwargs):
            if len(source.reads) >= 1:
                raise OSError('bad chunk')
            return original(*args, **kwargs)
        source.read_plane_region = broken
        job = ContrastEstimator(dataset)
        job.step()
        with pytest.raises(OSError, match='bad chunk'):
            job.step()
        assert job.result is None
        job.close()
        assert dataset.is_open


def test_repeated_seed_experiments_reduce_targeting_bias():
    # A tiny bright tile and large dark population; naive targeted pooling is
    # badly biased. Test the estimator's weighted CDF, not its display heuristic.
    source = GuidePyramid()
    cfg = ContrastConfig(draws=100, tile_size=8, bootstrap_replicates=0)
    weighted, naive = [], []
    threshold = 1000
    truth = np.mean(source.arrays[0][:, 0] <= threshold)
    with ImageDataset(source) as dataset:
        for seed in range(24):
            result = estimate_contrast(dataset, config=replace(cfg, seed=seed))
            weighted.append(result.cdf(threshold))
            naive.append(np.mean(result._values <= threshold))
    weighted_error = abs(np.mean(weighted) - truth)
    naive_error = abs(np.mean(naive) - truth)
    assert weighted_error < .01
    assert naive_error > weighted_error * 5


def test_benchmark_script_real_tiff_and_exhaustive_cap(tmp_path):
    import importlib.util
    import json
    from pathlib import Path
    script = Path(__file__).resolve().parents[1] / 'examples/benchmark_contrast.py'
    spec = importlib.util.spec_from_file_location('benchmark_contrast', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = tmp_path / 'benchmark.ome.tif'
    pixels = write_stack(path)
    result = module.run_benchmark(path, input_type='ome_tiff', seeds=(1,),
                                  config=ContrastConfig(draws=20, tile_size=8,
                                                        bootstrap_replicates=0),
                                  exhaustive_max_samples=pixels[:, 0].size)
    assert result['reference']['finite_samples'] == pixels[:, 0].size
    assert len(result['records']) == 2
    json.dumps(result, allow_nan=False)
    with pytest.raises(ValueError, match='exceeding cap'):
        module.run_benchmark(path, input_type='ome_tiff', seeds=(), exhaustive_max_samples=2)
