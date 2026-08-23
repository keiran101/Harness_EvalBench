"""Observability layer (design doc §4.3)."""

from .trace import Span, Trace, detect_drift

__all__ = ["Span", "Trace", "detect_drift"]
