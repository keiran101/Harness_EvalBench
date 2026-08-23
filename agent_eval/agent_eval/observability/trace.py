"""Lightweight observability (design doc §4.3): per-step spans over a trajectory
and a simple pass-rate drift detector for online sampling thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Span:
    name: str
    start_ns: int
    end_ns: Optional[int] = None
    metrics: Dict = field(default_factory=dict)


class Trace:
    """A session-level trace; evaluator scores get attached to spans so a bad result
    can be located down to the offending node (design doc §4.3)."""

    def __init__(self) -> None:
        self.spans: List[Span] = []

    def record_step(self, traj) -> "Trace":
        for i, st in enumerate(traj.steps):
            self.spans.append(Span(
                name=f"step_{i}:{st.action[:24]}",
                start_ns=0,
                metrics={"is_error": st.is_error,
                         "error_category": st.error_category or ""},
            ))
        return self

    def node_error_rate(self) -> float:
        if not self.spans:
            return 0.0
        return sum(1 for s in self.spans if s.metrics.get("is_error")) / len(self.spans)


def detect_drift(pass_history: List[float], window: int = 10, drop: float = 0.25) -> Dict:
    """Compare recent-window mean vs baseline-window mean of a pass-rate series.
    Alert when the drop exceeds `drop` (design doc §4.3: online drift detection)."""
    if len(pass_history) < 2 * window:
        return {"alert": False, "baseline": None, "recent": None, "reason": "insufficient history"}
    baseline = sum(pass_history[:window]) / window
    recent = sum(pass_history[-window:]) / window
    return {
        "alert": (baseline - recent) > drop,
        "baseline": baseline,
        "recent": recent,
        "reason": "recent pass-rate dropped below baseline" if (baseline - recent) > drop else "ok",
    }
