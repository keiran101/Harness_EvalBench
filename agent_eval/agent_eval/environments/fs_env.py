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
import tempfile
from typing import Any, Dict


class FsEnv:
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
