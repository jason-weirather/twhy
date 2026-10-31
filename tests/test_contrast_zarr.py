"""Required real NGFF-backend contrast checks; missing Zarr is not a passing skip."""
import numpy as np
import pytest

from omeify import open_dataset
from twhy import ContrastConfig, estimate_contrast
from zt_zarr_fixture import write_zarr_stack


@pytest.mark.parametrize('version', ['0.4', '0.5', '0.6'])
@pytest.mark.parametrize('pyramid', ['xy', 'xyz'])
def test_real_ngff_census_and_fixed_budget_sampler(tmp_path, version, pyramid):
    path = tmp_path / 'contrast.zarr'
    values, _ = write_zarr_stack(path, version=version, pyramid=pyramid)
    with open_dataset(path, input_type='ome_zarr') as dataset:
        result = estimate_contrast(dataset, channel=1, config=ContrastConfig(
            draws=1000, max_base_samples=100_000, bootstrap_replicates=0))
        assert result.exact
        np.testing.assert_array_equal(result._values, np.sort(values[:, 1].ravel()))
        sampled = estimate_contrast(dataset, channel=1, config=ContrastConfig(
            draws=32, tile_size=8, survey_reads=15, bootstrap_replicates=0))
        assert not sampled.exact and sampled.survey_samples > 0
        assert sampled._values.max() <= values[:, 1].max()
        assert sampled.sampled_samples <= 32 * 64
        assert dataset.is_open
