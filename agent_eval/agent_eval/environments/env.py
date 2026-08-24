"""The single unified Env class with pluggable storage backends.

Construction:
    Env(setup, backend="memory")   -> in-memory state (business domain)
    Env(setup, backend="disk")      -> real temp-dir filesystem (coding domain)
    Env(setup, backend="sql")       -> (future) real DB projection

`backend` comes from the dataset's `env.backend` field (schema, may be empty ->
defaults to "memory" for backward compatibility). Evaluator never names a concrete
backend; it only calls env_factory(instance), which builds Env with the right one.

Implementation note: the two proven backends are the existing ToolCallingEnv
(in-memory state machine) and FsEnv (real OS filesystem). Env wraps one of them and
forwards the uniform interface, so no check function, dataset, or agent code changes.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .base import BaseEnv
from .fs_env import FsEnv
from .tool_env import ToolCallingEnv


class Env(BaseEnv):
    """Unified environment. Picks a storage backend at construction time."""

    def __init__(self, setup: Dict[str, Any], backend: str = "memory"):
        super().__init__(setup)
        self.backend_name = backend
        if backend == "memory":
            self._impl = ToolCallingEnv(setup)
        elif backend == "disk":
            self._impl = FsEnv(setup)
        else:
            # Future backends register here; until then, fail loud not silent.
            raise ValueError(
                f"unknown env backend: {backend!r}. "
                f"Register it in environments/env.py Env.__init__."
            )

    def reset(self, setup: Optional[Dict[str, Any]] = None) -> None:
        self._impl.reset(setup)

    def get_state(self) -> Dict[str, Any]:
        return self._impl.get_state()

    def call_tool(self, name: str, **kwargs) -> str:
        return self._impl.call_tool(name, **kwargs)

    def cleanup(self) -> None:
        if hasattr(self._impl, "cleanup"):
            self._impl.cleanup()

    @property
    def cwd(self):
        """Expose the real working dir for disk-backed runs (used by pi bridge)."""
        return getattr(self._impl, "cwd", None)
