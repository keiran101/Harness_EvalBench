"""Pi coding-agent adapter: bridges the real pi harness into agent_eval.

pi is a Bun/TypeScript coding agent. This adapter drives it via a TS bridge
(pi-bridge.ts) that injects a deterministic fake ModelRuntime into pi's
AgentSession — the model layer is deterministic (no API key needed), while pi's
Harness layer (tool registry, tool execution, session/state management) is real.

Per design doc §2 (评估对象=模型+Harness 组合体): this evaluates the Harness side
of the pi+model composite with a fixed decision layer.

Strategy:
  reference : plan = the correct tool-call sequence for the task
  buggy     : plan = a deliberately wrong sequence (wrong content / dropped
              fields / over-deletion / no read), so failures are attributable
"""

from __future__ import annotations

import json
import subprocess
from typing import Dict, List, Optional

from .core import Step, Trajectory
from .datasets.templates import TaskInstance
from .environments.fs_env import FsEnv

BRIDGE_PATH = r"D:/MyFiles/agent-harness/pi-main/pi-bridge.ts"
BRIDGE_CWD = r"D:/MyFiles/agent-harness/pi-main"
NODE = "node"
NODE_FLAGS = ["--experimental-strip-types"]

# task -> reference tool-call plan (args reference inst.params placeholders)
_REF_PLANS: Dict[str, List[dict]] = {
    "fs_write_001": [
        {"tool": "write", "args": {"path": "report.txt", "content": "{TOKEN}"}},
    ],
    "fs_edit_001": [
        {"tool": "read", "args": {"path": "config.json"}},
        {"tool": "write", "args": {"path": "config.json",
                                   "content": '{"timeout": {VAL}, "host": "example.com"}'}},
    ],
    "fs_read_001": [
        {"tool": "read", "args": {"path": "info.txt"}},
    ],
    "fs_delete_001": [
        {"tool": "bash", "args": {"command": "rm tmp.log"}},
    ],
}

_BUGGY_PLANS: Dict[str, List[dict]] = {
    "fs_write_001": [
        {"tool": "write", "args": {"path": "report.txt", "content": "WRONG-TOKEN"}},
    ],
    "fs_edit_001": [
        {"tool": "write", "args": {"path": "config.json", "content": '{"timeout": {VAL}}'}},
    ],
    "fs_read_001": [],  # does not read; will answer from nothing
    "fs_delete_001": [
        {"tool": "bash", "args": {"command": "rm tmp.log keep.txt"}},
    ],
}

_ANSWERS: Dict[str, str] = {
    "fs_write_001": "done",
    "fs_edit_001": "done",
    "fs_read_001": "版本 {VER}",
    "fs_delete_001": "done",
}


def _fill_args(args, params: Dict[str, str]):
    """args 可以是 dict（填值）或 str（占位符替换）。"""
    if isinstance(args, str):
        out = args
        for p, val in params.items():
            out = out.replace("{" + p + "}", val)
        return out
    out = {}
    for k, v in args.items():
        if isinstance(v, str):
            for p, val in params.items():
                v = v.replace("{" + p + "}", val)
            out[k] = v
        else:
            out[k] = v
    return out


class PiAgentAdapter:
    def __init__(self, strategy: str = "reference", name: Optional[str] = None,
                 bridge_path: str = BRIDGE_PATH, bridge_cwd: str = BRIDGE_CWD):
        if strategy not in ("reference", "buggy"):
            raise ValueError(f"unknown strategy: {strategy}")
        self.strategy = strategy
        self.name = name or f"pi-{strategy}"
        self.bridge_path = bridge_path
        self.bridge_cwd = bridge_cwd

    def _call_bridge(self, cwd: str, instruction: str, plan: List[dict],
                     answer: str) -> dict:
        payload = json.dumps({"cwd": cwd, "instruction": instruction,
                              "plan": plan, "answer": answer})
        proc = subprocess.run(
            [NODE, *NODE_FLAGS, self.bridge_path],
            input=payload, capture_output=True, text=True,
            cwd=self.bridge_cwd, timeout=180, encoding="utf-8",
        )
        if proc.returncode != 0:
            raise RuntimeError(f"bridge failed rc={proc.returncode}: {proc.stderr[:500]}")
        return json.loads(proc.stdout)

    def run(self, instance: TaskInstance, env: FsEnv) -> Trajectory:
        tid = instance.template_id
        plans = _BUGGY_PLANS if self.strategy == "buggy" else _REF_PLANS
        plan = plans.get(tid, [])
        plan = [{**s, "args": _fill_args(s["args"], instance.params)} for s in plan]
        if self.strategy == "buggy" and tid == "fs_read_001":
            # 不读文件且答错 —— 归因才能落到 state_read 能力
            answer = "我不知道"
        else:
            answer = _fill_args(_ANSWERS.get(tid, "done"), instance.params)

        result = self._call_bridge(env.cwd, instance.instruction, plan, answer)

        traj = Trajectory()
        for st in result.get("trajectory", []):
            action = f"{st['tool']}:{json.dumps(st.get('args', {}), ensure_ascii=False)}"
            before = env.get_state()
            # bridge already executed the tool; approximate observation from state
            traj.steps.append(Step(
                action=action,
                observation=st.get("error") or "ok",
                state_before=before,
                state_after=env.get_state(),
                is_error=bool(st.get("isError")),
                error_category="tool_error" if st.get("isError") else None,
            ))
        traj.answer = result.get("answer") or None
        return traj
