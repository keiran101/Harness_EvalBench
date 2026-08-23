"""Closure loop (design doc §4.2/§7.9): bad cases are sunk into a RegressionStore,
and trajectory-prefix boundary sets are generated from them so regressions stay caught.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List

from ..core import Trajectory
from ..datasets.templates import TaskInstance


@dataclass
class BadCase:
    instance: TaskInstance
    trajectory: Trajectory
    reason: str


class RegressionStore:
    def __init__(self) -> None:
        self._cases: List[BadCase] = []

    def add_badcase(self, instance: TaskInstance, trajectory: Trajectory,
                    reason: str = "fail") -> None:
        self._cases.append(BadCase(instance=instance, trajectory=trajectory, reason=reason))

    def list_regression(self) -> List[BadCase]:
        return list(self._cases)

    def prefix_boundary_set(self, n: int) -> List[TaskInstance]:
        """Fix the first n steps of each bad trajectory into a boundary regression case
        (design doc §7.9: trajectory prefix boundary set).

        Returns TaskInstance (the single evaluation-unit schema) reusing the bad case's
        params/verifier/leak_guard, with expectation carrying the failure reason."""
        out: List[TaskInstance] = []
        for i, bc in enumerate(self._cases):
            prefix = " -> ".join(st.action for st in bc.trajectory.steps[:n]) or "(empty)"
            out.append(TaskInstance(
                id=f"reg_{i}_prefix{n}",
                template_id=bc.instance.template_id,
                tier=bc.instance.tier,
                capability=bc.instance.capability,
                instruction=f"从坏例 {bc.instance.id} 的前 {n} 步开始回归检查: {prefix}",
                setup=bc.instance.setup,
                params=bc.instance.params,
                verifier=bc.instance.verifier,
                leak_guard=bc.instance.leak_guard,
                tags=bc.instance.tags,
                expectation=bc.reason,
            ))
        return out
