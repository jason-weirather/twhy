"""Measure guided/uniform estimates against an optionally capped exhaustive reference.

Examples (run from the checkout with its declared dependencies installed):
    python examples/benchmark_contrast.py ~/Scratch/IDR/5514375.zarr --type ome_zarr
    python examples/benchmark_contrast.py small.ome.tif --type ome_tiff \
        --exhaustive-max-samples 8000000 > contrast-benchmark.json

No source image is written. JSON goes to stdout. Exhaustive validation is opt-in.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from math import prod
from time import perf_counter
import json
import platform

import numpy as np

from omeify import open_dataset
from twhy import ContrastConfig, estimate_contrast
from twhy.contrast import weighted_quantile


def _exhaustive(dataset, channel, cap):
    shape = dataset.levels[0]
    sizes = {name: shape.axis(name).size if shape.axis(name) else 1 for name in 'TZYX'}
    components = 3 if dataset.image_type == 'rgb' else 1
    total = prod(sizes.values()) * components
    if total > cap:
        raise ValueError(f'Exhaustive reference needs {total:,} samples, exceeding cap {cap:,}')
    parts = []
    for t in range(sizes['T']):
        for z in range(sizes['Z']):
            with dataset.plane(t=t if shape.axis('T') else None,
                               z=z if shape.axis('Z') else None) as image:
                for y in range(0, sizes['Y'], 256):
                    for x in range(0, sizes['X'], 256):
                        a = image.read_region(y, min(y + 256, sizes['Y']), x,
                                              min(x + 256, sizes['X']), channels=[channel])
                        parts.append(a[np.isfinite(a)].astype(np.float64))
    # Explicit small-data oracle. Sorting/concatenation require extra RAM beyond
    # the final sample array. This is not the production estimator's read path.
    return np.concatenate(parts)


def run_benchmark(path, *, input_type, channel=0, series=0, group='', seeds=(0, 1, 2),
                  config=None, exhaustive_max_samples=0):
    config = config or ContrastConfig()
    records = []
    estimates = []
    opened = perf_counter()
    with open_dataset(path, input_type=input_type, series=series, group=group) as dataset:
        open_seconds = perf_counter() - opened
        shape, axes = dataset.shape, dataset.axes
        for seed in seeds:
            # Alternate order by seed; clearing source payloads is not an OS-cache flush.
            methods = ('guided', 'uniform') if seed % 2 == 0 else ('uniform', 'guided')
            for method in methods:
                cfg = replace(config, seed=seed)
                if method == 'uniform':
                    cfg = replace(cfg, survey_reads=0, uniform_fraction=1.)
                dataset.clear_cache()
                before = dict(dataset.cache_info())
                start = perf_counter()
                estimate = estimate_contrast(dataset, channel=channel, config=cfg)
                record = dict(method=method, seed=seed, seconds=perf_counter() - start,
                              cache_before=before, cache_after=dict(dataset.cache_info()),
                              result=estimate.to_dict(include_histogram=False))
                records.append(record)
                estimates.append(estimate)
        reference = None
        if exhaustive_max_samples:
            start = perf_counter()
            values = _exhaustive(dataset, channel, exhaustive_max_samples)
            reference = {'finite_samples': int(values.size), 'scan_seconds': perf_counter() - start}
            if values.size:
                statistics_start = perf_counter()
                reference['ordinary_quantiles'] = [weighted_quantile(
                    values, np.ones(values.size), q) for q in
                    (config.lower_quantile, config.upper_quantile)]
                reference['ordinary_quantile_seconds'] = perf_counter() - statistics_start
                for record, estimate in zip(records, estimates, strict=True):
                    if estimate.window is None:
                        continue
                    low, high = estimate.window.lower, estimate.window.upper
                    above = values > high
                    scale = max(float(np.abs(values).max()), abs(low), np.finfo(float).tiny)
                    excess = np.maximum(values / scale - low / scale, 0.)
                    record['reference'] = {
                        'actual_upper_clipped_fraction': float(above.mean()),
                        'estimated_upper_clipped_fraction': estimate.clipped_fraction(high),
                        'actual_lower_clipped_fraction': float((values < low).mean()),
                        'actual_excess_mass_clipped_fraction': (
                            float(excess[above].sum() / excess.sum()) if excess.sum() else 0.),
                    }
    return {'schema': 'twhy.contrast-benchmark/1', 'python': platform.python_version(),
            'numpy': np.__version__, 'axes': axes, 'shape': shape,
            'open_seconds': open_seconds, 'records': records, 'reference': reference,
            'timing_scope': 'estimator only after metadata open; source payload cache cleared '
                            'before each run, not OS or remote caches; guided adds pilot work; '
                            'not an equal-total-I/O or cold-disk comparison'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path')
    parser.add_argument('--type', required=True, choices=('ome_tiff', 'ome_zarr'))
    parser.add_argument('--channel', type=int, default=0)
    parser.add_argument('--series', type=int, default=0)
    parser.add_argument('--group', default='')
    parser.add_argument('--seeds', type=int, nargs='+', default=[0, 1, 2])
    parser.add_argument('--draws', type=int, default=128)
    parser.add_argument('--base-samples', type=int, default=131072)
    parser.add_argument('--survey-samples', type=int, default=262144)
    parser.add_argument('--survey-reads', type=int, default=128)
    parser.add_argument('--bootstrap', type=int, default=48)
    parser.add_argument('--exhaustive-max-samples', type=int, default=0,
                        help='Opt-in reference cap; collection and sorting need extra RAM.')
    args = parser.parse_args()
    if args.exhaustive_max_samples < 0:
        parser.error('--exhaustive-max-samples must be nonnegative')
    config = ContrastConfig(draws=args.draws, max_base_samples=args.base_samples,
                            survey_samples=args.survey_samples, survey_reads=args.survey_reads,
                            bootstrap_replicates=args.bootstrap)
    result = run_benchmark(args.path, input_type=args.type, channel=args.channel,
                           series=args.series, group=args.group, seeds=args.seeds, config=config,
                           exhaustive_max_samples=args.exhaustive_max_samples)
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
