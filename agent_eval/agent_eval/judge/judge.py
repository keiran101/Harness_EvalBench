"""Judge layer (design doc §8): pluggable LLM-as-a-Judge.

- DummyJudge: rule-based, uses the deterministic verifier result + failure attribution.
  Zero dependencies, so the whole framework runs offline.
- LLMJudge: structure for real LLM judging (rubric + anchoring + bias correction +
  failure attribution as output). Requires an API key; raises NotImplementedError
  without one so offline runs never silently fake it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from ..core import Trajectory, first_error_step


@dataclass
class JudgeScore:
    overall: float                                  # 0..1
    rubric_scores: Dict[str, float] = field(default_factory=dict)
    failure_category: Optional[str] = None          # first failed FAIL_TO_PASS check
    first_error_step: Optional[int] = None          # attribution (design doc §8.5)


class Judge:
    name = "base"

    def score(self, instance, trajectory: Trajectory, final_state: dict,
              verification) -> JudgeScore:
        raise NotImplementedError


class DummyJudge(Judge):
    name = "dummy"

    def score(self, instance, trajectory: Trajectory, final_state: dict,
              verification) -> JudgeScore:
        fe = first_error_step(trajectory)
        if verification.passed:
            return JudgeScore(overall=1.0, rubric_scores={"task_success": 1.0},
                              first_error_step=fe)
        failed = [n for n, v in verification.fail_to_pass.items() if not v] + \
                 [n for n, v in verification.pass_to_pass.items() if not v]
        category = failed[0] if failed else "unknown"
        return JudgeScore(overall=0.0, rubric_scores={"task_success": 0.0},
                          failure_category=category, first_error_step=fe)


class LLMJudge(Judge):
    """LLM-as-a-Judge: structured rubric dims + weights, anchored scoring,
    positional/length/style bias corrections. Needs an API key."""
    name = "llm"

    def __init__(self, rubric: Optional[Dict[str, float]] = None,
                 model: Optional[str] = None, api_key: Optional[str] = None):
        self.rubric = rubric or {
            "task_completion": 0.5,
            "reasoning": 0.2,
            "tool_efficiency": 0.2,
            "clarity": 0.1,
        }
        self.model = model
        self.api_key = api_key

    def score(self, instance, trajectory: Trajectory, final_state: dict,
              verification) -> JudgeScore:
        if not self.api_key:
            raise NotImplementedError(
                "LLMJudge requires an API key; use DummyJudge for offline runs")
        # Real implementation would: prompt with rubric + anchor examples,
        # randomize order for pairwise, instruct "length is not a quality signal",
        # and emit failure attribution as part of the output.
        raise NotImplementedError("LLM call not implemented in this demo build")
