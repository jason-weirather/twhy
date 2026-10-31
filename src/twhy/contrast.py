"""Reusable stack/image contrast estimation, independent of the terminal viewer.

Omeify provides pixels and geometry. twhy estimates distributions and suggests
explicit display limits. See docs/contrast-estimation.md for statistical scope.
"""
from .contrast_sampling import ContrastEstimator, estimate_contrast
from .contrast_statistics import ContrastConfig, ContrastEstimate, weighted_quantile

__all__ = ["ContrastConfig", "ContrastEstimate", "ContrastEstimator", "estimate_contrast",
           "weighted_quantile"]
