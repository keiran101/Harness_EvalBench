"""Dataset Registry: versioned, tagged, leak-marked catalog of task templates (design doc §4.4).

Owns template registration, parametric instantiation, and verification delegation.
Supports filtering by tier / capability so a CI run can, e.g., "only the base tier".
"""

from __future__ import annotations

from typing import Dict, List, Optional

from .anti_leak import wire_leak_guard
from .templates import TaskInstance, TaskTemplate, instantiate
from .verifier import verify as _verify


class DatasetRegistry:
    def __init__(self, version: str = "0.1.0"):
        self.version = version
        self._templates: Dict[str, TaskTemplate] = {}

    @classmethod
    def with_base(cls, version: str = "0.1.0") -> "DatasetRegistry":
        """Build the base-tier registry. Every template is leak-wired (canary GUID
        embedded in instruction + freshness + isolation marker) before registration —
        the red line: leak_guard must never be an empty shell."""
        reg = cls(version)
        for t in _base_templates():
            wire_leak_guard(t)
            reg.register(t)
        return reg

    def register(self, template: TaskTemplate) -> None:
        self._templates[template.id] = template

    def list_templates(self, tier: Optional[str] = None,
                       capability: Optional[str] = None) -> List[TaskTemplate]:
        return [
            t for t in self._templates.values()
            if (tier is None or t.tier == tier)
            and (capability is None or t.capability == capability)
        ]

    def instantiate(self, tid: str, seed: int) -> TaskInstance:
        return instantiate(self._templates[tid], seed)

    def verify(self, instance: TaskInstance, final_state: dict, trajectory):
        return _verify(instance, final_state, trajectory)


def _base_templates():
    from .capabilities import list_base_templates
    return list_base_templates()
