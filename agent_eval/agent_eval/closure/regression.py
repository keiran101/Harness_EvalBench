"""Closure loop (design doc §4.2/§7.9): bad cases are sunk into a RegressionStore,
and trajectory-prefix boundary sets are generated from them so regressions stay caught.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List

from ..core import EvalCase, Trajectory


@dataclass
class BadCase:
    instance: Any
    trajectory: Trajectory
    reason: str


class RegressionStore:
    def __init__(self) -> None:
        self._cases: List[BadCase] = []

    def add_badcase(self, instance, trajectory: Trajectory, reason: str = "fail") -> None:
        self._cases.append(BadCase(instance=instance, trajectory=trajectory, reason=reason))

    def list_regression(self) -> List[BadCase]:
        return list(self._cases)

    def prefix_boundary_set(self, n: int) -> List[EvalCase]:
        """Fix the first n steps of each bad trajectory into a boundary regression case
        (design doc §7.9: trajectory prefix boundary set)."""
        out: List[EvalCase] = []
        for i, bc in enumerate(self._cases):
            prefix = " -> ".join(st.action for st in bc.trajectory.steps[:n]) or "(empty)"
            out.append(EvalCase(
                id=f"reg_{i}_prefix{n}",
                tier=bc.instance.tier,
                capability=bc.instance.capability,
                instruction=f"从坏例 {bc.instance.id} 的前 {n} 步开始回归检查: {prefix}",
                setup=bc.instance.setup,
                expectation=bc.reason,
            ))
        return out
