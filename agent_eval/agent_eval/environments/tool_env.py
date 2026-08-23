"""Tool-calling evaluation environment (design doc §6.1).

Exposes a small set of tools over an in-memory state machine, with deterministic
reset to a clean initial state and support for transient tool failure injection
(used by error_recovery templates via the hidden `_fail_first_call` setup flag).
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List


class ToolError(Exception):
    """A tool call failed (transient or permanent)."""


class ToolCallingEnv:
    def __init__(self, setup: Dict[str, Any]):
        self._setup = deepcopy(setup)
        self.state: Dict[str, Any] = deepcopy(setup)
        self._set_calls = 0
        self._fail_first = bool(setup.get("_fail_first_call", False))

    def reset(self, setup: Dict[str, Any] | None = None) -> None:
        if setup is not None:
            self._setup = deepcopy(setup)
        self.state = deepcopy(self._setup)
        self._set_calls = 0
        self._fail_first = bool(self._setup.get("_fail_first_call", False))

    def get_state(self) -> Dict[str, Any]:
        return deepcopy(self.state)

    def call_tool(self, name: str, **kwargs) -> str:
        if name == "read":
            return self._read(kwargs["path"])
        if name == "set":
            return self._set(kwargs["path"], kwargs["value"])
        if name == "delete":
            return self._delete(kwargs["path"])
        if name == "send":
            return self._send(kwargs["text"])
        if name == "clear":
            return self._clear(kwargs["table"])
        if name == "confirm":
            return f"confirmation recorded (awaiting user)"
        raise ToolError(f"unknown tool: {name}")

    # -- internals ---------------------------------------------------------

    def _read(self, path: List[str]) -> str:
        cur = self.state
        for k in path:
            cur = cur[k]
        return str(cur)

    def _set(self, path: List[str], value: Any) -> str:
        if self._fail_first and self._set_calls == 0:
            self._set_calls += 1
            raise ToolError("set failed: transient error, please retry")
        cur = self.state
        for k in path[:-1]:
            cur = cur[k]
        old = cur.get(path[-1]) if isinstance(cur, dict) else None
        if isinstance(old, bool):
            value = str(value).lower() in ("on", "true", "1")
        elif isinstance(old, int):
            value = int(value)
        cur[path[-1]] = value
        self._set_calls += 1
        return "ok"

    def _delete(self, path: List[str]) -> str:
        cur = self.state
        for k in path[:-1]:
            cur = cur[k]
        del cur[path[-1]]
        return "ok"

    def _send(self, text: str) -> str:
        self.state.setdefault("sent", []).append(text)
        return "ok"

    def _clear(self, table: str) -> str:
        self.state["tables"][table] = []
        return "ok"
