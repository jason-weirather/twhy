"""File-free pyramid semantics with the real dataset/Image/rendering interfaces.

These provider tests are independent of, not substitutes for, real Zarr I/O.
"""
from dataclasses import replace

import numpy as np
import pytest

from omeify import AxisInfo, DatasetLevel, ImageDataset, ImageLevel, ImageMetadata, PixelSize
from omeify.io.dataset_source import DatasetSourceBase
from twhy import ViewSession, Viewport


class MixedPyramid(DatasetSourceBase):
    """One XYZ-reduced level followed optionally by an exact-plane XY level."""

    def __init__(self, *, xy_level):
        super().__init__()
        t, c, z, y, x = np.indices((2, 2, 5, 32, 48))
        base = (t * 8000 + c * 2000 + z * 200 + y * 3 + x).astype(np.uint16)
        self.arrays = [base, base[:, :, ::2, ::2, ::2]]
        if xy_level:
            self.arrays.append(base[:, :, :, ::4, ::4])
        descriptors = []
        for index, array in enumerate(self.arrays):
            dz, dy = ((1, 1), (2, 2), (1, 4))[index]
            axes = tuple(AxisInfo(name, size, "time" if name == "T" else
                                  "channel" if name == "C" else "space")
                         for name, size in zip("TCZYX", array.shape, strict=True))
            axes = tuple(replace(axis, unit="µm", scale=2. * dz, origin=0.)
                         if axis.name == "Z" else axis for axis in axes)
            size = PixelSize(.5 * dy, .5 * dy, "µm")
            metadata = ImageMetadata("CYX", array.shape[1:2] + array.shape[-2:],
                                     base.dtype, channel_names=("A", "B"), pixel_size=size)
            descriptors.append(DatasetLevel(index, axes, metadata, index != 1))
        self.descriptors = tuple(descriptors)
        self.plane_level_indices = (0, 2) if xy_level else (0,)
        self.reads = []

    @property
    def dataset_levels(self):
        self._ensure_open()
        return self.descriptors

    def plane_metadata(self, *, z=None, t=None, level=0):
        metadata = self.descriptors[level].plane_metadata
        if level == 0 and len(self.descriptors) == 3:
            coarse = self.descriptors[2].plane_metadata
            metadata = replace(metadata, levels=(metadata.levels[0], ImageLevel(
                1, "CYX", coarse.shape, coarse.pixel_size,
                downsample_yx=(4., 4.), offset_yx=(0., 0.))))
        return metadata

    def read_plane_region(self, y0, y1, x0, x1, *, z, t, level, channels,
                          speculative=False):
        self.reads.append((t, z, level, channels))
        return np.stack([self.arrays[level][t, c, z, y0:y1, x0:x1] for c in channels])


@pytest.mark.parametrize("xy_level", [False, True])
def test_renderer_consumes_only_selected_images_exact_pyramid(xy_level):
    source = MixedPyramid(xy_level=xy_level)
    with ImageDataset(source) as dataset:
        for t, z in ((0, 4), (1, 3), (0, 4)):
            with dataset.plane(t=t, z=z) as image, ViewSession(image) as session:
                assert len(image.levels) == (2 if xy_level else 1)
                plan = session.plan(Viewport(0, 0, 48, 32), rows=8, columns=12, channels=(0, 1))
                samples = session.sample(plan)
                native = 2 if xy_level else 0
                assert all(read[2] == native for read in source.reads)
                if xy_level:
                    np.testing.assert_array_equal(samples.values, source.arrays[2][t, :, z])
                assert plan.level.index == (1 if xy_level else 0)
                source.reads.clear()
        # The excluded coarse observation remains available only when explicitly
        # selected at the dataset boundary. Nothing in twhy asks for it implicitly.
        with dataset.plane(t=0, z=1, native_level=1) as coarse:
            np.testing.assert_array_equal(coarse.asarray(), source.arrays[1][0, :, 1])
