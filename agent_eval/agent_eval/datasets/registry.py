"""Dataset Registry: versioned, tagged, leak-marked catalog of task templates (design doc §4.4).

Owns template registration, parametric instantiation, and verification delegation.
Supports filtering by tier / capability so a CI run can, e.g., "only the base tier".

Two dataset sources are supported:
  - with_base()      : built-in base templates (code, used as the default/fixture set)
  - from_file / from_dir : EXTERNALIZED datasets stored as JSON/YAML (the recommended
                           way to grow the catalog — pure data, version-controllable)
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Optional

from .anti_leak import wire_leak_guard
from .templates import TaskInstance, TaskTemplate, from_dict, instantiate, to_dict
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

    @classmethod
    def from_file(cls, path: str, version: str = "0.1.0",
                  leak_wire: bool = True) -> "DatasetRegistry":
        """Load templates from a single JSON file. leak_wire=True applies the
        canary/freshness/isolation red line on load (keeps stored files clean)."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        reg = cls(version)
        templates = data["templates"] if isinstance(data, dict) and "templates" in data else data
        for d in templates:
            t = from_dict(d)
            if leak_wire:
                wire_leak_guard(t)
            reg.register(t)
        return reg

    @classmethod
    def from_dir(cls, directory: str, version: str = "0.1.0",
                 leak_wire: bool = True) -> "DatasetRegistry":
        """Load every *.json under a directory (recursively)."""
        reg = cls(version)
        for root, _, files in os.walk(directory):
            for fn in sorted(files):
                if fn.endswith(".json"):
                    sub = cls.from_file(os.path.join(root, fn), version=version, leak_wire=leak_wire)
                    for tid, t in sub._templates.items():
                        reg._templates[tid] = t
        return reg

    @classmethod
    def from_dirs(cls, *directories: str, version: str = "0.1.0",
                  leak_wire: bool = True) -> "DatasetRegistry":
        """Merge several file-isolated dataset directories into ONE pool.

        This is the key to 'datasets stay file-isolated, evaluation never splits':
        each domain keeps its own folder (data/biz, data/coding, data/sql ...),
        but they are merged here into a single registry so Evaluator treats them
        as one unified set with one report.
        """
        reg = cls(version)
        for d in directories:
            sub = cls.from_dir(d, version=version, leak_wire=leak_wire)
            for tid, t in sub._templates.items():
                if tid in reg._templates:
                    raise ValueError(f"duplicate template id across dirs: {tid}")
                reg._templates[tid] = t
        return reg

    def merge(self, other: "DatasetRegistry") -> "DatasetRegistry":
        """Merge another registry's templates into this one (in place)."""
        for tid, t in other._templates.items():
            if tid in self._templates:
                raise ValueError(f"duplicate template id: {tid}")
            self._templates[tid] = t
        return self

    def register(self, template: TaskTemplate) -> None:
        self._templates[template.id] = template

    def list_templates(self, tier: Optional[str] = None,
                       capability: Optional[str] = None) -> List[TaskTemplate]:
        return [
            t for t in self._templates.values()
            if (tier is None or t.tier == tier)
            and (capability is None or capability in t.capability)
        ]

    def instantiate(self, tid: str, seed: int) -> TaskInstance:
        return instantiate(self._templates[tid], seed)

    def verify(self, instance: TaskInstance, final_state: dict, trajectory):
        return _verify(instance, final_state, trajectory)


def _base_templates():
    from .capabilities import list_base_templates
    return list_base_templates()
