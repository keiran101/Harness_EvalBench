"""Metrics layer (design doc §5)."""
from .metrics import pass_at_k, pass_k, pass_consecutive_k, summarize
from .process import (
    action_legality, path_efficiency, retrieval_coverage,
    cost_latency, safety_compliance, robustness, aggregate_averages, PROCESS_KEYS,
)

__all__ = [
    "pass_at_k", "pass_k", "pass_consecutive_k", "summarize",
    "action_legality", "path_efficiency", "retrieval_coverage",
    "cost_latency", "safety_compliance", "robustness",
    "aggregate_averages", "PROCESS_KEYS",
]
