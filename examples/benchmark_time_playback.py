"""Profile OME Z/T frame sampling and terminal-art preparation without a terminal.

Run from a twhy checkout with Omeify installed::

    python examples/benchmark_time_playback.py movie.ome.tiff > movie-frames.csv

The result uses the same ViewSession sampling and renderer stages as the viewer,
without startup contrast surveys, idle overview construction, terminal writes,
or playback dwell time. Compare timepoints before/after a slowdown to distinguish
source-region I/O (including resampling) from glyph preparation. This is not a
measurement of the complete interactive terminal or a codec-only benchmark.
"""
from __future__ import annotations

import argparse
import csv
from statistics import median
import sys
from time import perf_counter

from omeify import open_dataset

from twhy.startup_overview import startup_fit
from twhy.text_renderer import TextRenderer
from twhy.view_session import ViewSession
from twhy.viewer.rendering import terminal_lines


def profile(path: str, *, input_type: str = "ome_tiff", series: int = 0,
            z_index: int | None = None, first: int = 0, stop: int | None = None,
            columns: int = 100, rows: int = 30, mode: str = "blocks",
            cache_mib: int = 64, stream=None) -> list[dict]:
    """Produce per-frame timings, preserving the source's existing cache policy."""
    if stream is None:
        stream = sys.stdout
    if first < 0 or (stop is not None and stop <= first):
        raise ValueError("Choose a nonempty, zero-based half-open T range")
    if columns < 1 or rows < 1 or cache_mib < 0:
        raise ValueError("Columns/rows must be positive; cache MiB cannot be negative")

    renderer = TextRenderer(mode=mode, color=True)
    fields = ("t", "setup_ms", "sampling_ms", "render_ms", "total_ms",
              "source_loads", "source_hits", "source_evictions", "source_resident_mib",
              "sampled_overview", "source_samples")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    timings = []
    with open_dataset(path, input_type=input_type, series=series,
                      cache_bytes=cache_mib * 1024 * 1024) as dataset:
        depth = dataset.axis_info("Z")
        z = (None if depth is None else depth.size // 2 if z_index is None else z_index)
        if depth is None and z_index is not None:
            raise ValueError("This source has no Z axis")
        time_axis = dataset.axis_info("T")
        if time_axis is None or time_axis.size < 2:
            raise ValueError("Source needs a time axis containing multiple frames")
        final = time_axis.size if stop is None else min(stop, time_axis.size)
        if first >= final:
            raise ValueError("First timepoint is beyond the available sequence")

        # The viewer locks the initial intensity window; do not re-estimate it
        # on every timepoint in this probe. No extra I/O for frame 0 is added.
        fixed_window = None
        for t in range(first, final):
            begin = perf_counter()
            with dataset.plane(z=z, t=t) as image, ViewSession(
                    image, cache_mib=0, overview_cache_mib=0) as session:
                viewport, _ = startup_fit(session, renderer, columns=columns, rows=rows,
                                          channels=(0,))
                sample_rows, sample_columns = renderer.sample_shape(
                    columns=columns, rows=rows)
                plan = session.plan(viewport, rows=sample_rows, columns=sample_columns,
                                    channels=(0,), allow_sampled_overview=True)
                setup = perf_counter()
                samples = session.sample(plan)
                sampled = perf_counter()
                styles = session.prepare_styles(samples, windows=[fixed_window])
                if fixed_window is None:
                    fixed_window = styles[0].window
                frame = session.render(samples, styles=styles, renderer=renderer,
                                       columns=columns, rows=rows)
                terminal_lines(frame)
                rendered = perf_counter()
            source = dataset.cache_info()
            entry = dict(
                t=t,
                setup_ms=round((setup - begin) * 1000, 3),
                sampling_ms=round((sampled - setup) * 1000, 3),
                render_ms=round((rendered - sampled) * 1000, 3),
                total_ms=round((rendered - begin) * 1000, 3),
                source_loads=source["loads"], source_hits=source["hits"],
                source_evictions=source["evictions"],
                source_resident_mib=round(source["resident_bytes"] / 1024 ** 2, 3),
                sampled_overview=plan.sampled_overview is not None,
                source_samples=plan.source_samples,
            )
            writer.writerow(entry)
            timings.append(entry)
    if len(timings) >= 6:
        third = len(timings) // 3
        early, late = timings[:third], timings[-third:]
        print(f"T playback profiling: {len(timings)} frames; early/late median total "
              f"{median(a['total_ms'] for a in early):g}/"
              f"{median(a['total_ms'] for a in late):g} ms; "
              f"early/late median sampling "
              f"{median(a['sampling_ms'] for a in early):g}/"
              f"{median(a['sampling_ms'] for a in late):g} ms; "
              "terminal output and playback wait are excluded.", file=sys.stderr)
    return timings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="Local OME-TIFF or OME-Zarr dataset")
    parser.add_argument("--type", dest="input_type", default="ome_tiff",
                        choices=("ome_tiff", "ome_zarr"))
    parser.add_argument("--series", type=int, default=0)
    parser.add_argument("--z-index", type=int)
    parser.add_argument("--first", type=int, default=0)
    parser.add_argument("--stop", type=int, help="Exclusive T end index")
    parser.add_argument("--columns", type=int, default=100)
    parser.add_argument("--rows", type=int, default=30)
    parser.add_argument("--mode", choices=("blocks", "simple", "detail", "shape"),
                        default="blocks")
    parser.add_argument("--cache-mib", type=int, default=64)
    args = parser.parse_args()
    profile(args.path, input_type=args.input_type, series=args.series,
            z_index=args.z_index, first=args.first, stop=args.stop,
            columns=args.columns, rows=args.rows, mode=args.mode,
            cache_mib=args.cache_mib)


if __name__ == "__main__":
    main()
