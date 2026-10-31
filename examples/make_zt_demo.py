"""Write a small, deterministic Z/T browsing demo through the public Omeify API.

Creates TIFF, XY-Zarr and XYZ-Zarr; no downloads or patient data. Output products
must not exist. Run from the checkout with the updated Omeify installed:
    python examples/make_zt_demo.py --output-directory ~/Scratch/twhy-zt-demo
"""
from __future__ import annotations

from pathlib import Path

import click
import numpy as np


def make_values() -> np.ndarray:
    """Changing discs/rings distinguish depth, time and channels visually."""
    t, z, y, x = np.indices((4, 9, 128, 192))
    center_x, center_y = 65 + 13 * t, 64 + 3 * (z - 4)
    radius = 28 - 4 * np.abs(z - 4)
    distance = np.hypot(x - center_x, y - center_y)
    disc = np.clip(radius + 1 - distance, 0, 1)
    ring = np.exp(-((distance - radius - 12) / 2.5) ** 2)
    # A small moving reference square is visible even on the first/last Z plane.
    square = ((x > 140 + 2 * t) & (x < 150 + 2 * t) &
              (y > 15 + 5 * z) & (y < 24 + 5 * z))
    return np.stack((np.rint(40000 * disc), np.rint(25000 * ring + 30000 * square)),
                    axis=1).astype(np.uint16)


def write_demo(directory: Path) -> dict[str, Path]:
    from omeify import AxisInfo, ImageDataset, OMETiffWriter, OMEZarrWriter, PixelSize
    from omeify import open_dataset

    directory = Path(directory).expanduser()
    outputs = {"tiff": directory / "time-depth.ome.tif",
               "xy": directory / "time-depth-xy.zarr",
               "xyz": directory / "time-depth-xyz.zarr"}
    for path in outputs.values():
        if path.exists() or path.is_symlink():
            raise FileExistsError(f"Refusing to replace {path}")
    directory.mkdir(parents=True, exist_ok=True)
    values = make_values()
    with ImageDataset.from_array(
        values, axes="TCZYX", channel_names=("Disc", "Ring and marker"),
        pixel_size=PixelSize(.5, .5, "µm"),
        axis_info=(AxisInfo("T", 4, "time", "s", 10., 0.),
                   AxisInfo("Z", 9, "space", "µm", 2., 0.)),
    ) as dataset:
        OMETiffWriter(outputs["tiff"], compression="Deflate", tile_size=32,
                      pyramid_levels=2, overwrite=False).write_dataset(dataset)
        for policy in ("xy", "xyz"):
            OMEZarrWriter(outputs[policy], tile_size=32, pyramid_levels=2).write_dataset(
                dataset, pyramid_axes=policy)
    for kind, path in outputs.items():
        with open_dataset(path, input_type="ome_tiff" if kind == "tiff" else "ome_zarr") as ds:
            for t in range(4):
                for z in range(9):
                    with ds.plane(t=t, z=z) as image:
                        np.testing.assert_array_equal(image.asarray(), values[t, :, z])
        click.echo(str(path))
    return outputs


@click.command()
@click.option("--output-directory", type=click.Path(path_type=Path), required=True)
def main(output_directory: Path) -> None:
    """Create public-safe Z/T fixtures; existing products are never overwritten."""
    write_demo(output_directory)


if __name__ == "__main__":
    main()
