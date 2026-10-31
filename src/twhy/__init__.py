"""Reusable image-to-text rendering. The terminal UI is imported separately."""

from ._version import resolve_version
from .contrast import ContrastConfig, ContrastEstimate, ContrastEstimator, estimate_contrast
from .histogram import HistogramView, render_histogram
from .compositing import ChannelStyle, compose_channels
from .image_input import open_image
from .intensity_window import IntensityWindow, estimate_window
from .view_info import ReadBudgetExceeded
from .resampling import resample_image
from .text_image import TextImage
from .text_renderer import TextRenderer
from .view_session import ViewSession
from .viewport import Viewport

__version__ = resolve_version()

__all__ = [
    "ChannelStyle", "ContrastConfig", "ContrastEstimate", "ContrastEstimator",
    "HistogramView", "IntensityWindow", "ReadBudgetExceeded",
    "TextImage", "TextRenderer", "ViewSession", "Viewport", "__version__",
    "compose_channels", "estimate_contrast", "estimate_window", "open_image",
    "render_histogram", "resample_image",
]
