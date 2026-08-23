"""Metrics engine (design doc §5): Pass@k (capability ceiling) vs Pass^k (reliability),
plus report discipline (k scope, sample size, env differences, unfinished items).
"""

from __future__ import annotations

from typing import Dict, List, Optional

from ..core import EvalReport, first_error_step


def pass_at_k(successes: List[bool], k: int) -> float:
    """Capability ceiling: at least 1 success in k independent samples (design doc §5.1)."""
    if not successes:
        return 0.0
    return 1.0 if any(successes) else 0.0


def pass_k(successes: List[bool], k: int) -> float:
    """Business reliability: stable pass rate across k samples (design doc §5.1)."""
    if not successes:
        return 0.0
    return sum(1 for s in successes if s) / len(successes)


def pass_consecutive_k(successes: List[bool], k: int) -> float:
    """Strict consecutive-k pass: all k samples must pass."""
    return 1.0 if successes and all(successes) else 0.0


def summarize(reports: List[EvalReport], k: int, k_scope: str = "same-task k independent samples",
              env_note: str = "tool-calling env, deterministic verifier") -> Dict:
    """Aggregate per-case reports into a dataset-level summary with report discipline
    (design doc §5.4: k scope, sample size, env differences, unfinished).

    Pass@k / Pass^k are computed per task group (the k samples of the SAME task),
    then averaged across tasks — reporting an "any success over the whole dataset"
    would be meaningless.
    """
    n = len(reports)
    groups: Dict[str, List[EvalReport]] = {}
    for r in reports:
        key = r.case_id.rsplit("__s", 1)[0] if "__s" in r.case_id else r.case_id
        groups.setdefault(key, []).append(r)

    per_group = {}
    by_cap: Dict[str, List[bool]] = {}
    first_errors: Dict[str, int] = {}
    for gid, reps in groups.items():
        successes = [r.passed for r in reps]
        per_group[gid] = {
            "pass_at_k": pass_at_k(successes, k),
            "pass_k": pass_k(successes, k),
            "pass_consecutive_k": pass_consecutive_k(successes, k),
        }
        for r in reps:
            by_cap.setdefault(r.capability, []).append(r.passed)
            if r.first_error_step is not None:
                first_errors[r.case_id] = r.first_error_step

    def _avg(field: str) -> float:
        return round(sum(g[field] for g in per_group.values()) / len(per_group), 4) \
            if per_group else 0.0

    return {
        "k": k,
        "k_scope": k_scope,
        "sample_size": n,
        "env": env_note,
        "overall": {
            "pass_at_k": _avg("pass_at_k"),
            "pass_k": _avg("pass_k"),
            "pass_consecutive_k": _avg("pass_consecutive_k"),
            "first_error_cases": len(first_errors),
        },
        "by_capability": {
            cap: {
                "n": len(vals),
                "pass_k": pass_k(vals, k),
            }
            for cap, vals in by_cap.items()
        },
        "unfinished": [r.case_id for r in reports if r.notes == "unfinished"],
    }
