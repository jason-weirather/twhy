"""Small, bounded prepublication sampling for interactive intensity windows.

This is a viewer policy only. The full public estimator retains its default
statistical configuration and can be invoked independently of the terminal.
"""
from __future__ import annotations

from dataclasses import replace

from ..contrast_statistics import ContrastConfig


# Cooperative wall-time budget: one noninterruptible backend read may exceed it.
# No visible image is ever rewindowed automatically after this deadline.
STARTUP_CONTRAST_SECONDS = 1.25


def initial_contrast_config(config: ContrastConfig) -> ContrastConfig:
    """Use the same estimator with fewer region reads, not coarse histogram bins.

    The broad pyramid pilot still guides high-resolution base-pixel sampling;
    its reduced pixels never enter the final intensity distribution. Bootstrap
    uncertainty is left for the full estimator requested by H/A.
    """
    return replace(config, draws=min(config.draws, 24),
                   max_base_samples=min(config.max_base_samples, 24_576),
                   survey_reads=min(config.survey_reads, 12),
                   survey_samples=min(config.survey_samples, 24_576),
                   bootstrap_replicates=0)
