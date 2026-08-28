"""OpenCode coding-agent adapter: drives the real opencode CLI into agent_eval.

opencode is a Bun/TypeScript coding agent (Vercel AI SDK based). We drive it via
its real non-interactive CLI (`opencode run --format json`) as a subprocess —
the full product path (session loop, tool registry, permission handling, fs
tools) executes for real. The decision LLM is a REAL OpenAI-compatible endpoint
(LLM_EVAL_BASE_URL / LLM_EVAL_MODEL, default the local gemma QAT server),
configured through a custom provider (`eval-local` in config/opencode_eval.json,
@ai-sdk/openai-compatible).

The CLI emits one JSON event per stdout line; we parse tool_use / text / error /
session.status(idle) events into Trajectory steps and the final answer.
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Dict, List, Optional

from ..core import Step, Trajectory
from ..datasets.templates import TaskInstance
from ..environments.env import Env

CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config")
EVAL_CONFIG = os.path.join(CONFIG_DIR, "opencode_eval.json")
OPENCODE_ROOT = os.environ.get("OPENCODE_ROOT", r"D:/MyFiles/agent-harness/opencode-dev")
BUN = os.environ.get("BUN_BIN", r"D:/common/develop/Nodejs/node_global/node_modules/bun/bin/bun.exe")
LLM_BASE_URL = os.environ.get("LLM_EVAL_BASE_URL", "http://8.134.63.180:7010")
LLM_MODEL = os.environ.get("LLM_EVAL_MODEL", "google/gemma-4-12b-qat")
PROVIDER_ID = "eval-local"
EVAL_CONFIG_CONTENT = None  # rendered lazily from env at call time


def _render_eval_config(base_url: str, model: str) -> str:
    """Render the opencode config JSON with the current LLM endpoint + model.

    Written to a temp file per adapter instance so concurrent runs (if any)
    never race on one shared file; the CLI reads it via OPENCODE_CONFIG.
    Includes the slim-tools plugin (tool schema pruning) because the local
    endpoint's n_ctx=4096 cannot fit opencode's full 30+ tool schemas.
    """
    cfg = {
        "provider": {
            PROVIDER_ID: {
                "npm": "@ai-sdk/openai-compatible",
                "name": "Eval Local LLM",
                "options": {"baseURL": base_url.rstrip("/") + "/v1", "apiKey": "dummy"},
                "models": {model: {"name": model.split("/")[-1]}},
            }
        },
        "plugin": ([os.path.join(CONFIG_DIR, "opencode_slim.ts")]
                   if os.environ.get("OPENCODE_SLIM", "1") not in ("0", "false", "off", "")
                   else []),
        "permission": {
            "edit": "allow",
            "bash": "allow",
            "write": "allow",
            "skill": "deny",
        },
    }
    return json.dumps(cfg, ensure_ascii=False)


class OpenCodeAgentAdapter:
    def __init__(self, name: Optional[str] = None,
                 opencode_root: str = OPENCODE_ROOT, bun: str = BUN,
                 llm_base_url: str = LLM_BASE_URL, llm_model: str = LLM_MODEL,
                 timeout: int = 900):
        self.name = name or f"opencode-{llm_model}"
        self.opencode_root = opencode_root
        self.bun = bun
        self.llm_base_url = llm_base_url
        self.llm_model = llm_model
        self.model = llm_model
        self.timeout = timeout
        # 工具面口径：slim=注入 opencode_slim.ts 裁剪工具 schema（默认开）；
        # full=满血工具面（设 OPENCODE_SLIM=0 关闭）。与 _build_config 的判定一致。
        self.slim = os.environ.get("OPENCODE_SLIM", "1") not in ("0", "false", "off", "")
        self.tool_surface = "slim" if self.slim else "full"
        self._cfg_path: Optional[str] = None

    # -- CLI 驱动 -----------------------------------------------------------

    def _cli_cmd(self, cwd: str, instruction: str) -> List[str]:
        entry = os.path.join(self.opencode_root, "packages", "opencode", "src", "index.ts")
        return [
            self.bun, "run", "--cwd",
            os.path.join(self.opencode_root, "packages", "opencode"),
            "--conditions=browser", entry, "run",
            "--format", "json",
            "--dir", cwd,
            "--model", f"{PROVIDER_ID}/{self.llm_model}",
            "--auto",
            instruction,
        ]

    def _call_cli(self, cwd: str, instruction: str) -> dict:
        import tempfile
        cfg_content = _render_eval_config(self.llm_base_url, self.llm_model)
        fd, cfg_path = tempfile.mkstemp(suffix=".json", prefix="opencode_eval_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(cfg_content)
        self._cfg_path = cfg_path
        env = {
            **os.environ,
            "OPENCODE_CONFIG": cfg_path,
            "OPENCODE_DISABLE_AUTOUPDATE": "1",
            "OPENCODE_TELEMETRY": "off",
            "NO_COLOR": "1",
        }
        try:
            proc = subprocess.run(
                self._cli_cmd(cwd, instruction),
                capture_output=True, text=True, env=env,
                timeout=self.timeout, encoding="utf-8", errors="replace",
                # bun 的 preload（@opentui/solid/preload）从进程 cwd 解析，
                # 必须落在 opencode 包目录（含 node_modules）
                cwd=os.path.join(self.opencode_root, "packages", "opencode"),
            )
        finally:
            try:
                os.unlink(cfg_path)
            except OSError:
                pass

        events: List[dict] = []
        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue

        return self._parse_events(events, proc.returncode, proc.stderr)

    def _parse_events(self, events: List[dict], rc: int, stderr: str) -> dict:
        """Parse the opencode run JSON event stream into a trajectory.

        Event types of interest (from packages/opencode/src/cli/cmd/run.ts):
          tool_use   : {part:{tool, state:{status: completed|error, input, error}}}
          text       : {part:{text}} — final assistant text parts
          error      : session-level error
          session.status idle : loop ends (implicit; we just stop at EOF)
        """
        steps: List[dict] = []
        texts: List[str] = []
        err: Optional[str] = None
        for ev in events:
            t = ev.get("type")
            if t == "tool_use":
                part = ev.get("part") or {}
                state = part.get("state") or {}
                status = state.get("status")
                steps.append({
                    "tool": part.get("tool", "unknown"),
                    # opencode 事件里工具实参在 state.input（part 层无 input）
                    "args": state.get("input") or part.get("input") or {},
                    "isError": status == "error",
                    "error": state.get("error") if status == "error" else None,
                })
            elif t == "text":
                part = ev.get("part") or {}
                txt = (part.get("text") or "").strip()
                if txt:
                    texts.append(txt)
            elif t == "error":
                e = ev.get("error") or {}
                err = str(e.get("message") or e.get("data") or e)
        if rc != 0 and not steps and not err:
            err = f"opencode run failed rc={rc}: {stderr[:500]}"
        return {"steps": steps, "answer": "\n".join(texts).strip() or None, "error": err}

    # -- 框架接口 -----------------------------------------------------------

    def run(self, instance: TaskInstance, env: Env) -> Trajectory:
        cwd = env.cwd
        instruction = instance.instruction
        result = self._call_cli(cwd, instruction)

        traj = Trajectory()
        for st in result.get("steps", []):
            action = f"{st['tool']}:{json.dumps(st.get('args', {}), ensure_ascii=False)}"
            before = env.get_state()
            traj.steps.append(Step(
                action=action,
                observation=st.get("error") or "ok",
                state_before=before,
                state_after=env.get_state(),
                is_error=bool(st.get("isError")),
                error_category="tool_error" if st.get("isError") else None,
            ))
        traj.answer = result.get("answer")
        return traj
