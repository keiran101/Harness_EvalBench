"""Orchestrator (design doc §4.2): instance -> env -> agent -> verifier -> metrics -> report.

Runs every selected template k times (independent samples, seed-shifted), verifies the
final environment state with the deterministic dual-check verifier, attaches a judge
score, and aggregates a report with k-scope / sample-size / env / unfinished discipline.
"""

from __future__ import annotations

import logging
import sys
import time
from time import perf_counter
from typing import Any, Callable, Dict, List, Optional

from .core import EvalReport, Trajectory, first_error_step, _traj_to_dict

logger = logging.getLogger(__name__)


class EvalAborted(RuntimeError):
    """评估因连续相同执行失败（疑似环境问题）被主动中止。"""

    def __init__(self, reason: str, signature: str):
        super().__init__(reason)
        self.reason = reason
        self.signature = signature
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
                 env_factory: Optional[Callable] = None,
                 max_consecutive_failures: int = 3,
                 failure_cooldown_s: float = 10.0):
        self.registry = registry
        self.agent = agent
        self.k = k
        self.seed_base = seed_base
        self.judge = judge or DummyJudge()
        # Environment-agnostic: default factory dispatches by instance.env.backend.
        self.env_factory = env_factory or make_env_factory()
        # 连崩熔断：连续相同错误达阈值则判疑似环境问题、主动中止（避免空耗慢端点）
        self.max_consecutive_failures = max_consecutive_failures
        self.failure_cooldown_s = failure_cooldown_s
        self._fail_streak = 0
        self._fail_sig: Optional[str] = None

    def _fail_signature(self, exc: Exception) -> str:
        """归一化错误签名：异常类名 + 首行消息（折叠空白），用于判定『相同错误』。"""
        msg = " ".join(str(exc).split())[:160]
        return f"{type(exc).__name__}:{msg}"

    def _crash_metrics(self, failure_category: str) -> Dict[str, Any]:
        """case 执行崩溃时的指标占位：process 指标标 available=False 以免污染均值。"""
        na: Dict[str, Any] = {"value": None, "available": False,
                              "detail": f"case crashed ({failure_category})"}
        return {
            "judge": 0.0,
            "failure_category": failure_category,
            "action_legality": dict(na),
            "path_efficiency": dict(na),
            "retrieval_coverage": dict(na),
            "cost_latency": dict(na),
            "safety_compliance": dict(na),
        }

    def run_case(self, tid: str) -> List[EvalReport]:
        """Run one template k times; each run is a fresh deterministic episode.

        单样本若执行崩溃（超时 / 进程崩溃 / OOM / RuntimeError 等），记该样本为
        unfinished 失败并继续；连续出现相同错误达阈值则判疑似环境问题、主动中止。
        """
        reports: List[EvalReport] = []
        for i in range(self.k):
            inst = self.registry.instantiate(tid, seed=self.seed_base + i)
            env = self.env_factory(inst)
            t0 = perf_counter()
            try:
                traj = self.agent.run(inst, env)
            except Exception as exc:
                # 不吞 BaseException（保留 KeyboardInterrupt / SystemExit 的中断能力）
                sig = self._fail_signature(exc)
                if sig == self._fail_sig:
                    self._fail_streak += 1
                else:
                    self._fail_sig = sig
                    self._fail_streak = 1
                logger.warning("case %s sample %d 执行崩溃[%s]，连续 %d 次：%r",
                               inst.id, i, sig, self._fail_streak, exc)
                traj = Trajectory(steps=[], answer=None)
                reports.append(EvalReport(
                    case_id=inst.id, tier=inst.tier, capability=inst.capability,
                    passed=False, first_error_step=None,
                    metrics=self._crash_metrics("harness_error"),
                    notes="unfinished", traj=traj,
                ))
                env.cleanup()
                if self._fail_streak >= self.max_consecutive_failures:
                    raise EvalAborted(
                        f"连续 {self._fail_streak} 个样本执行失败（相同错误 {sig}），"
                        f"疑似环境问题，已中止评估", sig)
                if self.failure_cooldown_s > 0:
                    time.sleep(self.failure_cooldown_s)
                continue
            # 正常完成（无论 verify 是否通过）：重置连崩计数
            self._fail_streak = 0
            self._fail_sig = None
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
                traj=traj,
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
        aborted: Optional[str] = None
        for t in templates:
            try:
                reps = self.run_case(t.id)
            except EvalAborted as ae:
                aborted = ae.reason
                logger.error("评估中止：%s", ae.reason)
                break
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
                # Full per-seed trajectories for audit/replay.
                "trajectories": [_traj_to_dict(r.traj) for r in reps],
            }
            all_reports.extend(reps)

        summary = summarize(all_reports, self.k)
        summary["agent"] = getattr(self.agent, "name", "unknown")
        # 工具面口径（slim/full），由各 adapter 在 __init__ 自识别，便于评估分析区分。
        summary["tool_surface"] = getattr(self.agent, "tool_surface", "unknown")
        summary["templates"] = per_template
        summary["process_metrics"] = aggregate_averages(all_reports)
        summary["robustness"] = {tid: per_template[tid]["robustness"]
                                 for tid in per_template}
        summary["aborted"] = aborted
        return summary
