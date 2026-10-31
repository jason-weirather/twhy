"""Independently specified tiny NGFF stores; no Omeify writer under test."""
from __future__ import annotations

import numpy as np


def write_zarr_stack(path, *, version="0.5", axes="tczyx", pyramid="xy", sharded=False):
    import zarr  # A required dependency. Do not turn missing Zarr into a passing skip.

    sizes = dict(t=3, c=2, z=5, y=32, x=48)
    coords = np.indices(tuple(sizes[a] for a in axes))
    weights = dict(t=6000, c=2000, z=200, y=3, x=1)
    values = sum(coords[i] * weights[a] for i, a in enumerate(axes)).astype(np.uint16)
    fmt = 2 if version == "0.4" else 3
    root = zarr.open_group(str(path), mode="w", zarr_format=fmt)
    steps = ([dict(x=1, y=1, z=1), dict(x=2, y=2, z=1)] if pyramid == "xy" else
             [dict(x=1, y=1, z=1), dict(x=2, y=2, z=1), dict(x=4, y=4, z=2)])
    datasets = []
    arrays = []
    for index, step in enumerate(steps):
        pixels = values[tuple(slice(None, None, step.get(axis, 1)) for axis in axes)]
        chunks = tuple(16 if axis in "yx" else 2 if axis in "cz" else 3 for axis in axes)
        storage = ({"compressor": None} if fmt == 2 else
                   {"compressors": [], "dimension_names": tuple(axes)})
        if sharded:
            storage["shards"] = tuple(n * 2 if axis in "yx" else n
                                       for axis, n in zip(axes, chunks, strict=True))
        array = root.create_array(str(index), shape=pixels.shape, dtype=pixels.dtype,
                                  chunks=chunks, **storage)
        array[:] = pixels
        arrays.append(pixels)
        scale = [dict(t=30., c=1., z=2., y=.5, x=.5)[a] * step.get(a, 1) for a in axes]
        shift = [dict(z=2., y=.5, x=.5).get(a, 0.) * (step.get(a, 1) - 1) / 2
                 for a in axes]
        transforms = [{"type": "scale", "scale": scale},
                      {"type": "translation", "translation": shift}]
        if version == "0.6":
            transforms = [{"type": "sequence", "transformations": transforms,
                           "input": {"path": str(index)}, "output": {"name": "physical"}}]
        datasets.append({"path": str(index), "coordinateTransformations": transforms})
    axes_meta = [{"name": a, "type": "time" if a == "t" else "channel" if a == "c" else "space",
                  **({"unit": "second"} if a == "t" else
                     {"unit": "micrometer"} if a in "xyz" else {})} for a in axes]
    ms = {"datasets": datasets}
    if version == "0.6":
        ms["coordinateSystems"] = [{"name": "physical", "axes": axes_meta}]
    else:
        ms["axes"] = axes_meta
    ome = {"multiscales": [ms]}
    if "c" in axes:
        ome["omero"] = {"channels": [{"label": name} for name in ("DNA", "Marker")]}
    if version == "0.4":
        ms["version"] = "0.4"
        root.attrs.update(ome)
    else:
        root.attrs.update({"ome": {"version": version, **ome}})
    root.store.close()
    return values, arrays
