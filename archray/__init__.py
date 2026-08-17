"""ArchRay — architecture analysis for source repositories."""

from .config import Thresholds
from .engine import VERSION, analyze_source, build_report

__all__ = ["Thresholds", "analyze_source", "build_report", "VERSION"]
__version__ = VERSION
