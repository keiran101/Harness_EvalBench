"""Orchestrator (design doc §4.2): instance -> env -> agent -> verifier -> metrics -> report.

Runs every selected template k times (independent samples, seed-shifted), verifies the
final environment state with the deterministic dual-check verifier, attaches a judge
score, and aggregates a report with k-scope / sample-size / env / unfinished discipline.
"""

from __future__ import annotations

from time import perf_counter
from typing import Callable, Dict, List, Optional

from .core import EvalReport, first_error_step
from .datasets.registry import DatasetRegistry
from .environments.env import Env
from .judge.judge import DummyJudge, Judge
from .metrics.metrics import (
    pass_at_k,
    pass_consecutive_k,
    pass_k,
    summarize,
)
from .metrics.process import (
    action_legality, path_efficiency, retrieval_coverage,
    cost_latency, safety_compliance,
)
from .metrics.process import robustness, aggregate_averages


def make_env_factory(default_backend: str = "memory") -> Callable:
    """Default env factory: picks a backend per instance via its `env.backend`
    field (schema; may be empty -> default_backend for backward compatibility).

    Evaluation NEVER splits by domain: every template from the merged registry
    flows through this single factory, so business + coding + future domains run
    in one unified Evaluator loop with one report.
    """
    def factory(instance):
        backend = (instance.env or {}).get("backend", default_backend)
        return Env(instance.setup, backend=backend)
    return factory


class Evaluator:
    def __init__(self, registry: DatasetRegistry, agent, k: int = 4,
                 seed_base: int = 0, judge: Optional[Judge] = None,
                 env_factory: Optional[Callable] = None):
        self.registry = registry
        self.agent = agent
        self.k = k
        self.seed_base = seed_base
        self.judge = judge or DummyJudge()
        # Environment-agnostic: default factory dispatches by instance.env.backend.
        self.env_factory = env_factory or make_env_factory()

    def run_case(self, tid: str) -> List[EvalReport]:
        """Run one template k times; each run is a fresh deterministic episode."""
        reports: List[EvalReport] = []
        for i in range(self.k):
            inst = self.registry.instantiate(tid, seed=self.seed_base + i)
            env = self.env_factory(inst)
            t0 = perf_counter()
            traj = self.agent.run(inst, env)
            traj.latency_ms = (perf_counter() - t0) * 1000.0
            final_state = env.get_state()
            vr = self.registry.verify(inst, final_state, traj)
            judge_score = self.judge.score(inst, traj, final_state, vr)
            fe = first_error_step(traj) if not vr.passed else None
            metrics = {
                "judge": judge_score.overall,
                "failure_category": judge_score.failure_category,
                "action_legality": action_legality(traj, inst, vr),
                "path_efficiency": path_efficiency(traj, inst),
                "retrieval_coverage": retrieval_coverage(traj, inst),
                "cost_latency": cost_latency(traj),
                "safety_compliance": safety_compliance(traj, inst, vr),
            }
            reports.append(EvalReport(
                case_id=inst.id,
                tier=inst.tier,
                capability=inst.capability,
                passed=vr.passed,
                first_error_step=fe,
                metrics=metrics,
            ))
            env.cleanup()
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
                "robustness": robustness(successes, self.k, t.capability),
            }
            all_reports.extend(reps)

        summary = summarize(all_reports, self.k)
        summary["agent"] = getattr(self.agent, "name", "unknown")
        summary["templates"] = per_template
        summary["process_metrics"] = aggregate_averages(all_reports)
        summary["robustness"] = {tid: per_template[tid]["robustness"]
                                 for tid in per_template}
        return summary
