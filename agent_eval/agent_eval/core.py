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
