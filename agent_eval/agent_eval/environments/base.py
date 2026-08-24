"""Universal evaluation environment interface (design doc §6, unified 2026-08-23).

One Env to rule them all: a single `Env` class exposes a uniform interface
(reset / get_state / call_tool / cleanup). The *storage backend* is pluggable:

  - "memory" : state lives in an in-process dict (fast, deterministic, no IO).
               get_state() returns the nested dict as-is -> business-domain
               checks (state_eq / len_eq / irreversible_without_confirm ...) work.
  - "disk"   : state lives in a real temp dir on the OS filesystem.
               get_state() scans the tree -> {relpath: content} -> coding-domain
               checks (file_* / json_field_eq ...) work. Real bash/IO capable.
  - future   : "sql" / "http" / "dom" backends can be added without touching
               Evaluator, datasets, or check functions.

Why this shape (and NOT merging the two old envs into one class with if-branches):
the *source of truth* differs per domain (process memory vs real disk vs real DB),
so the storage implementations must stay separate. What we unify is the *access
contract* (one Env interface + one Evaluator flow + one schema field `env.backend`),
not the storage shape. Each backend returns whatever final_state shape its domain's
checks expect; the verifier only consumes a `passed: bool`, so cross-domain
comparability at the metric layer is preserved for free.

Datasets stay file-isolated (data/biz, data/coding, data/sql ...). Evaluation never
splits by domain: Evaluator pulls every template from one merged registry and lets
env_factory pick the right backend per instance.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class BaseEnv:
    """Uniform contract every environment backend implements.

    Evaluator and agents only ever talk to this interface — they never see which
    backend is active. Subclasses implement the storage-specific bits.
    """

    def __init__(self, setup: Dict[str, Any]):
        self._setup = setup

    def reset(self, setup: Optional[Dict[str, Any]] = None) -> None:
        raise NotImplementedError

    def get_state(self) -> Dict[str, Any]:
        """Return the final environment state. Shape is backend-specific:
        memory -> nested dict; disk -> {relpath: content}."""
        raise NotImplementedError

    def call_tool(self, name: str, **kwargs) -> str:
        """Execute one tool call; return an observation string."""
        raise NotImplementedError

    def cleanup(self) -> None:
        """Release external resources (e.g. temp dirs). No-op for memory."""
        pass
