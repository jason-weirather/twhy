"""Create two independently navigable, multidimensional OME-TIFF image series.

Synthetic only; no microscope data or Omeify concat is needed. Each series
has 4 time points, 7 Z sections, 2 channels and its own visible pattern.
Existing output files are never replaced. Use d / [ / ] in twhy to browse.
"""

from __future__ import annotations

from pathlib import Path

import click
import numpy as np
import tifffile


def make_values() -> tuple[np.ndarray, np.ndarray]:
    """Distinguishable TCZYX uint16 stacks without large RAM requirements."""
    t, z, y, x = np.indices((4, 7, 96, 128))
    cx = 45 + 10 * t
    cy = 40 + 4 * (z - 3)
    radius = 20 - 3 * abs(z - 3)
    distance = np.hypot(x - cx, y - cy)
    disc = np.clip(radius + 1 - distance, 0, 1)
    ring = np.exp(-((distance - radius - 8) / 2.5) ** 2)
    base = np.stack((np.rint(42000 * disc), np.rint(26000 * ring)),
                    axis=1).astype(np.uint16)
    return base, np.roll(base, shift=28, axis=-1)


def write_demo(destination: Path) -> Path:
    """Write a single TIFF with two full TCZYX OME Image series."""
    destination = Path(destination).expanduser()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(f"Refusing to overwrite {destination}")
    if not destination.parent.is_dir():
        raise FileNotFoundError(f"Create output directory first: {destination.parent}")
    for name, data in zip(("series_one", "series_two"), make_values(), strict=True):
        assert data.shape == (4, 2, 7, 96, 128)
    with tifffile.TiffWriter(destination, ome=True) as writer:
        for name, pixels in zip(("series_one", "series_two"), make_values(), strict=True):
            writer.write(
                pixels, photometric="minisblack", tile=(32, 32),
                compression="deflate",
                metadata={
                    "axes": "TCZYX", "Name": name,
                    "Channel": {"Name": ["Disc", "Ring and marker"]},
                    "PhysicalSizeX": .5, "PhysicalSizeY": .5,
                    "PhysicalSizeXUnit": "µm", "PhysicalSizeYUnit": "µm",
                    "PhysicalSizeZ": 2., "PhysicalSizeZUnit": "µm",
                    "TimeIncrement": 10., "TimeIncrementUnit": "s",
                },
            )
    return destination


@click.command()
@click.option("-o", "--output", type=click.Path(dir_okay=False, path_type=Path),
              required=True, help="New OME-TIFF path; never overwrites.")
def main(output: Path) -> None:
    try:
        click.echo(str(write_demo(output)))
    except (FileExistsError, FileNotFoundError) as error:
        raise click.ClickException(str(error)) from error


if __name__ == "__main__":
    main()
