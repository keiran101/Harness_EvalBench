"""Core data models shared by every layer of the Agent evaluation framework.

Evaluation paradigm (design doc §3): the unit is a *Task* / *Trajectory* (episode),
not a single QA turn. Success is verified against the **final environment state**,
not against text. A trajectory is the first-class citizen so that failure attribution
(first-error-step) is possible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Step:
    """One action+observation in a trajectory. ``is_error`` marks an unacceptable action."""
    action: str
    observation: str
    state_before: dict
    state_after: dict
    is_error: bool = False
    error_category: Optional[str] = None
    # Optional natural-language / structured answer the agent emitted at this step
    answer: Optional[str] = None


@dataclass
class Trajectory:
    steps: list[Step] = field(default_factory=list)
    # Agent's final answer (used by state_read / clarify / confirm verifiers)
    answer: Optional[str] = None
    # ---- process-metrics fields (2026-08-24) ----
    # Round-level wall-clock latency of agent.run(), filled by Evaluator (ms).
    latency_ms: Optional[float] = None
    # Reserved: total LLM/tool requests in the round (adapters may set; may be None).
    request_count: Optional[int] = None

    def first_error_step(self) -> Optional[int]:
        for i, s in enumerate(self.steps):
            if s.is_error:
                return i
        return None


def first_error_step(traj: Trajectory) -> Optional[int]:
    return traj.first_error_step()


@dataclass
class VerificationResult:
    """Outcome of running the verifier on a final state."""
    passed: bool
    fail_to_pass: dict        # name -> bool  (must become True after success)
    pass_to_pass: dict        # name -> bool  (must stay True)
    must_not_do: dict = field(default_factory=dict)  # name -> bool  (HARD VETO)


@dataclass
class EvalReport:
    case_id: str
    tier: str
    capability: list          # list of capabilities exercised
    passed: bool
    first_error_step: Optional[int]
    metrics: dict = field(default_factory=dict)
    notes: str = ""
    # Full trajectory for this case (action/observation/answer/latency), kept so the
    # report is auditable. Adapters discard raw sessions after parsing; this is the
    # structured residue we retain for replay/attribution.
    traj: Optional["Trajectory"] = None


def _traj_to_dict(traj) -> dict:
    """Serialize a Trajectory into a JSON-friendly dict (steps + answer + timing)."""
    if traj is None:
        return {}
    return {
        "answer": traj.answer,
        "latency_ms": traj.latency_ms,
        "request_count": traj.request_count,
        "steps": [
            {
                "action": s.action,
                "observation": s.observation,
                "is_error": s.is_error,
                "error_category": s.error_category,
                "answer": s.answer,
                "state_before": s.state_before,
                "state_after": s.state_after,
            }
            for s in traj.steps
        ],
    }
