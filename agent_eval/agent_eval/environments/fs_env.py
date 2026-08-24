"""Real-filesystem evaluation environment (design doc §6.1, coding domain).

The coding-domain environment is the actual OS filesystem inside a temp dir.
- setup: {relpath: content} -> files written before the agent runs
- final state: get_state() scans the tree -> {relpath: content}
- Used with the pi bridge: the agent (pi, via subprocess) operates on env.cwd
  with its real tools (read/write/edit/bash...).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from typing import Any, Dict

from .base import BaseEnv
from .tool_env import ToolError


class FsEnv(BaseEnv):
    def __init__(self, setup: Dict[str, Any]):
        self._tmp = tempfile.mkdtemp(prefix="pi-eval-")
        self.cwd = self._tmp
        self._setup = dict(setup)
        self.prepare(setup)

    def prepare(self, setup: Dict[str, Any]) -> None:
        """Write the initial file tree. Existing files are overwritten."""
        for rel, content in setup.items():
            full = os.path.join(self.cwd, rel)
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as f:
                f.write(content)

    def get_state(self) -> Dict[str, str]:
        """Scan the tree -> {relpath: content}."""
        out: Dict[str, str] = {}
        for root, _, files in os.walk(self.cwd):
            for fn in files:
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, self.cwd).replace("\\", "/")
                with open(full, "r", encoding="utf-8", errors="replace") as f:
                    out[rel] = f.read()
        return out

    def call_tool(self, name: str, **kwargs) -> str:
        """Framework-internal tool execution (disk backend). The pi bridge drives
        the env externally; this lets a generic in-process agent also run coding
        tasks through the same Env interface. bash runs for real in env.cwd."""
        if name == "write":
            full = os.path.join(self.cwd, kwargs["path"])
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8") as f:
                f.write(kwargs["content"])
            return "ok"
        if name == "read":
            full = os.path.join(self.cwd, kwargs["path"])
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                return f.read()
        if name == "delete":
            full = os.path.join(self.cwd, kwargs["path"])
            if os.path.isdir(full):
                shutil.rmtree(full, ignore_errors=True)
            elif os.path.exists(full):
                os.remove(full)
            return "ok"
        if name == "bash":
            proc = subprocess.run(kwargs["command"], shell=True, cwd=self.cwd,
                                  capture_output=True, text=True, encoding="utf-8")
            return (proc.stdout + proc.stderr).strip() or "ok"
        raise ToolError(f"unknown tool: {name}")

    def reset(self, setup: Dict[str, Any] | None = None) -> None:
        if setup is not None:
            self._setup = dict(setup)
        # clear tree
        for name in os.listdir(self.cwd):
            p = os.path.join(self.cwd, name)
            shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
        self.prepare(self._setup)

    def cleanup(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)
