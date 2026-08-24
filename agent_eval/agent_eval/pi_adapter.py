"""Pi coding-agent adapter: bridges the real pi harness into agent_eval (data-driven).

pi is a Bun/TypeScript coding agent. This adapter drives it via a TS bridge
(pi-bridge.ts) with two model-decision modes:

  mode="plan" (default): injects a deterministic fake ModelRuntime into pi's
    AgentSession — the model layer is deterministic (no API key needed), while
    pi's Harness layer (tool registry, tool execution, session/state management)
    is real. Per design doc §2 this evaluates the Harness side with a fixed
    decision layer. The tool-call sequence comes from `reference_plan`.
      strategy="reference": execute instance.reference_plan as-is (correct)
      strategy="buggy"    : perturb the plan (wrong value / over-delete / no
                            read) so failures are attributable

  mode="llm": replaces the fake ModelRuntime's streamSimple with a REAL LLM call
    (OpenAI-compatible endpoint). Evaluates the composite 「pi Harness × real
    model」 — pi's real tool registry/session loop + gemma-4-12b-qat decisions.
    The reference_plan is NOT used for decisions (only kept for reference).

Env: PI_ROOT (pi source root), LLM_EVAL_BASE_URL / LLM_EVAL_MODEL (llm mode).
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Dict, List, Optional

from .core import Step, Trajectory
from .datasets.templates import TaskInstance
from .environments.env import Env

BRIDGE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bridge", "pi_bridge.ts")
PI_ROOT = os.environ.get("PI_ROOT", r"D:/MyFiles/agent-harness/pi-main")
LLM_BASE_URL = os.environ.get("LLM_EVAL_BASE_URL", "http://8.134.63.180:7010")
LLM_MODEL = os.environ.get("LLM_EVAL_MODEL", "google/gemma-4-12b-qat")
NODE = "node"
NODE_FLAGS = ["--experimental-strip-types"]


def _fill_args(args, params: Dict[str, str]):
    """args 可以是 dict（填值）或 str（占位符替换）。"""
    if isinstance(args, str):
        out = args
        for p, val in params.items():
            out = out.replace("{" + p + "}", val).replace("[" + p + "]", val)
        return out
    out = {}
    for k, v in args.items():
        if isinstance(v, str):
            for p, val in params.items():
                v = v.replace("{" + p + "}", val).replace("[" + p + "]", val)
            out[k] = v
        else:
            out[k] = v
    return out


def _perturb_plan(plan: List[dict], params: Dict[str, str]) -> List[dict]:
    """Generic buggy perturbation: make the plan fail in an attributable way.
    - write: replace content with a WRONG marker (never matches the verifier)
    - bash rm/mv: append a protected file to the command (over-deletion)
    - read-only plans: drop every step (agent answers from nothing)
    Returns a perturbed plan list."""
    out = []
    for s in plan:
        if s["tool"] == "write":
            out.append({**s, "args": {**s["args"], "content": "WRONG-" + str(s["args"].get("content", ""))}})
        elif s["tool"] == "bash":
            cmd = s["args"].get("command", "")
            if "rm" in cmd or "mv" in cmd:
                # over-delete: touch a sentinel file that must NOT exist at the end
                out.append({**s, "args": {"command": cmd + " && echo leaked > leaked.txt"}})
            else:
                out.append(s)
        else:
            out.append(s)
    if not out:
        return []  # no steps -> agent answers without doing anything
    return out


class PiAgentAdapter:
    def __init__(self, strategy: str = "reference", name: Optional[str] = None,
                 bridge_path: str = BRIDGE_PATH, pi_root: str = PI_ROOT,
                 mode: str = "plan", llm_base_url: str = LLM_BASE_URL,
                 llm_model: str = LLM_MODEL, llm_max_tokens: int = 2048):
        if mode not in ("plan", "llm"):
            raise ValueError(f"unknown mode: {mode}")
        if strategy not in ("reference", "buggy"):
            raise ValueError(f"unknown strategy: {strategy}")
        self.mode = mode
        self.strategy = strategy
        self.name = name or (f"pi-llm-{llm_model}" if mode == "llm" else f"pi-{strategy}")
        self.bridge_path = bridge_path
        self.pi_root = pi_root
        self.llm_base_url = llm_base_url
        self.llm_model = llm_model
        self.llm_max_tokens = llm_max_tokens

    def _call_bridge(self, cwd: str, instruction: str, plan: List[dict],
                     answer: str) -> dict:
        payload: dict = {"cwd": cwd, "instruction": instruction}
        if self.mode == "llm":
            payload["plan"] = []
            payload["answer"] = "done"
            payload["llm"] = {"baseUrl": self.llm_base_url, "model": self.llm_model,
                              "maxTokens": self.llm_max_tokens}
        else:
            payload["plan"] = plan
            payload["answer"] = answer
        env = {**os.environ, "PI_ROOT": self.pi_root}
        proc = subprocess.run(
            [NODE, *NODE_FLAGS, self.bridge_path],
            input=json.dumps(payload), capture_output=True, text=True,
            env=env, timeout=600, encoding="utf-8",
        )
        if proc.returncode != 0:
            raise RuntimeError(f"bridge failed rc={proc.returncode}: {proc.stderr[:800]}")
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise RuntimeError(f"bridge bad output: {proc.stdout[:500]} / {proc.stderr[:300]}")

    def run(self, instance: TaskInstance, env: Env) -> Trajectory:
        """Drive the real pi harness. plan mode executes the dataset's reference
        plan (or its perturbed buggy variant); llm mode lets the real model decide.
        env is the unified Env (disk backend for coding).
        """
        plan = list(instance.reference_plan or [])
        if self.mode == "plan":
            if self.strategy == "buggy":
                plan = _perturb_plan(plan, instance.params)
                answer = "我不知道" if not plan else _fill_args(instance.reference_answer, instance.params)
            else:
                answer = _fill_args(instance.reference_answer, instance.params) or "done"
            plan = [{**s, "args": _fill_args(s["args"], instance.params)} for s in plan]
        else:
            answer = "done"

        cwd = env.cwd if env.backend_name == "disk" else env.cwd
        result = self._call_bridge(cwd, instance.instruction, plan, answer)

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
