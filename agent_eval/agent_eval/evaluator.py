"""Orchestrator (design doc §4.2): instance -> env -> agent -> verifier -> metrics -> report.

Runs every selected template k times (independent samples, seed-shifted), verifies the
final environment state with the deterministic dual-check verifier, attaches a judge
score, and aggregates a report with k-scope / sample-size / env / unfinished discipline.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from .core import EvalReport, first_error_step
from .datasets.registry import DatasetRegistry
from .environments.tool_env import ToolCallingEnv
from .judge.judge import DummyJudge, Judge
from .metrics.metrics import (
    pass_at_k,
    pass_consecutive_k,
    pass_k,
    summarize,
)


class Evaluator:
    def __init__(self, registry: DatasetRegistry, agent, k: int = 4,
                 seed_base: int = 0, judge: Optional[Judge] = None):
        self.registry = registry
        self.agent = agent
        self.k = k
        self.seed_base = seed_base
        self.judge = judge or DummyJudge()

    def run_case(self, tid: str) -> List[EvalReport]:
        """Run one template k times; each run is a fresh deterministic episode."""
        reports: List[EvalReport] = []
        for i in range(self.k):
            inst = self.registry.instantiate(tid, seed=self.seed_base + i)
            env = ToolCallingEnv(inst.setup)
            traj = self.agent.run(inst, env)
            final_state = env.get_state()
            vr = self.registry.verify(inst, final_state, traj)
            judge_score = self.judge.score(inst, traj, final_state, vr)
            # Failure attribution only for FAILED trajectories (a successful retry's
            # transient tool error is not an agent error).
            fe = first_error_step(traj) if not vr.passed else None
            reports.append(EvalReport(
                case_id=inst.id,
                tier=inst.tier,
                capability=inst.capability,
                passed=vr.passed,
                first_error_step=fe,
                metrics={"judge": judge_score.overall,
                         "failure_category": judge_score.failure_category},
            ))
        return reports

    def evaluate(self, tids: Optional[List[str]] = None,
                 tier: Optional[str] = None) -> Dict:
        templates = self.registry.list_templates(tier=tier)
        if tids:
            templates = [t for t in templates if t.id in tids]

        all_reports: List[EvalReport] = []
        per_template: Dict = {}
        for t in templates:
            reps = self.run_case(t.id)
            successes = [r.passed for r in reps]
            per_template[t.id] = {
                "tier": t.tier,
                "capability": t.capability,
                "pass_at_k": pass_at_k(successes, self.k),
                "pass_k": pass_k(successes, self.k),
                "pass_consecutive_k": pass_consecutive_k(successes, self.k),
                "first_error_steps": [r.first_error_step for r in reps
                                      if r.first_error_step is not None],
            }
            all_reports.extend(reps)

        summary = summarize(all_reports, self.k)
        summary["agent"] = getattr(self.agent, "name", "unknown")
        summary["templates"] = per_template
        return summary
