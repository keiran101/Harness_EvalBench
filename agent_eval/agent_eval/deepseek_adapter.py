"""DeepSeek Harness (dsh) coding-agent adapter: drives `dsh --profile headless`.

dsh is a Cordis-plugin agent harness from DeepSeek AI. Its product one-shot
mode (`dsh --profile headless "<task>"`) creates a fresh persisted session,
drives the task to quiescence, prints the final assistant text, and exits.
We drive it as a subprocess from the task workspace (cwd = env.cwd), with the
decision LLM pointed at a REAL OpenAI-compatible endpoint via
DEEPSEEK_BASE_URL (LLM_EVAL_BASE_URL, default the local gemma QAT server) and a
`--patch` overlay that re-pins the model id + disables thinking.

Trajectory: the headless runner flushes the session to JSONL
(`.sessions/`, plaintext when DSH_SNAPSHOT is set); we parse tool-call events
from that log after the run and clean it up (the coding verifier checks the
workspace directory must not gain stray entries).
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import tempfile
from typing import Dict, List, Optional

from .core import Step, Trajectory
from .datasets.templates import TaskInstance
from .environments.env import Env

DSH_ROOT = os.environ.get("DSH_ROOT", r"D:/MyFiles/agent-harness/deepseek-harness-master")
NODE = os.environ.get("NODE_BIN", r"C:/Users/86132/.workbuddy/binaries/node/versions/22.22.2/node.exe")
LLM_BASE_URL = os.environ.get("LLM_EVAL_BASE_URL", "http://8.134.63.180:7010")
LLM_MODEL = os.environ.get("LLM_EVAL_MODEL", "google/gemma-4-12b-qat")

_PATCH_TEMPLATE = """\
# agent_eval overlay: pin the decision model to the local LLM endpoint.
- id: llm-deepseek
  config:
    thinking: disabled
    reasoningEffort: off
    models:
      - id: {model}
        contextWindow: 128000
- id: agent-spine
  config:
    agents:
      - id: main
        provider: deepseek-official
        model: {model}
- id: session-persistence-jsonl
  config:
    root: !!js dshHomePath('sessions')
    compression: none
"""


class DeepSeekHarnessAdapter:
    def __init__(self, name: Optional[str] = None,
                 dsh_root: str = DSH_ROOT, node: str = NODE,
                 llm_base_url: str = LLM_BASE_URL, llm_model: str = LLM_MODEL,
                 timeout: int = 600):
        self.name = name or f"dsh-{llm_model}"
        self.dsh_root = dsh_root
        self.node = node
        self.llm_base_url = llm_base_url
        self.llm_model = llm_model
        self.model = llm_model
        self.timeout = timeout

    # -- CLI 驱动 -----------------------------------------------------------

    def _cli_cmd(self, cwd: str, instruction: str, patch_path: str) -> List[str]:
        # 用构建产物（apps/cli/lib/bin.js，无需 tsx）
        bin_js = os.path.join(self.dsh_root, "apps", "cli", "lib", "bin.js")
        return [
            self.node, bin_js,
            "--profile", "headless",
            "--patch", patch_path,
            instruction,
        ]

    def _call_cli(self, cwd: str, instruction: str) -> dict:
        patch_content = _PATCH_TEMPLATE.format(model=self.llm_model)
        fd, patch_path = tempfile.mkstemp(suffix=".yml", prefix="dsh_eval_patch_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(patch_content)
        # Isolate dsh's home (sessions/profile dirs) inside the task workspace so
        # the JSONL trajectory is findable AND the task dir stays verifier-clean
        # after we remove it before returning.
        dsh_home = os.path.join(cwd, ".dsh-eval-home")
        env = {
            **os.environ,
            "DSH_HOME": dsh_home,
            "DEEPSEEK_API_KEY": "dummy",
            "DEEPSEEK_BASE_URL": self.llm_base_url.rstrip("/") + "/v1",
            "DSH_SNAPSHOT": "replay",   # JSONL persistence in plaintext (no zstd)
            "DSH_TELEMETRY_DISABLED": "1",
            "DSH_PERMISSION_MODE": "danger-full-access",  # 无人值守：approval=never + 沙箱全放行（dsh 官方 headless/CI 模式）
            "CI": "true",               # 非交互（避免 pnpm 交互确认挂起）
            "NO_COLOR": "1",
        }
        timed_out = False
        try:
            proc = subprocess.run(
                self._cli_cmd(cwd, instruction, patch_path),
                capture_output=True, text=True, env=env,
                timeout=self.timeout, encoding="utf-8", errors="replace",
                cwd=cwd,
            )
        except subprocess.TimeoutExpired as exc:
            # 单 case 超时不应拖崩整个评估：记为失败（error="timeout"），继续
            timed_out = True
            answer = None
            error = f"dsh run timed out after {self.timeout}s"
            steps = self._parse_sessions(dsh_home)
            if os.path.isdir(dsh_home):
                try:
                    shutil.rmtree(dsh_home)
                except OSError:
                    pass
            return {"steps": steps, "answer": answer, "error": error}
        finally:
            try:
                os.unlink(patch_path)
            except OSError:
                pass

        answer = proc.stdout.strip() or None
        error = None
        if proc.returncode != 0:
            error = (proc.stderr.strip() or "dsh run failed")[:800]
        steps = self._parse_sessions(dsh_home)
        # Clean the isolated home so the workspace stays verifier-clean.
        if os.path.isdir(dsh_home):
            try:
                shutil.rmtree(dsh_home)
            except OSError:
                pass
        return {"steps": steps, "answer": answer, "error": error}

    def _parse_sessions(self, dsh_home: str) -> List[dict]:
        """Parse tool-call events from the flushed JSONL session log.

        Session artifacts live under $DSH_HOME/sessions (base bundle mounts
        session-persistence-jsonl at dshHomePath('sessions')). We scan the
        newest JSONL file(s) and extract assistant tool-call blocks.
        """
        steps: List[dict] = []
        base = os.path.join(dsh_home, "sessions")
        files = sorted(glob.glob(os.path.join(base, "**", "*.jsonl"), recursive=True))
        for fp in files:
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            rec = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        steps.extend(self._record_to_steps(rec))
            except OSError:
                continue
        return steps

    @staticmethod
    def _record_to_steps(rec: dict) -> List[dict]:
        """Extract tool-call steps from one dsh session JSONL record.

        Event shapes (from @deepseek-ai/dsh-session events):
          tool/call   : {data:{callId, name, arguments(JSON string)}}
          tool/result : {data:{message.content:[{type:"tool-result",
                         toolCallId, content:[...], isError}]}}
        We emit one step per tool/call and back-patch isError when the
        matching tool/result arrives.
        """
        out: List[dict] = []
        rtype = rec.get("type")
        if rtype == "tool/call":
            d = rec.get("data") or {}
            args_raw = d.get("arguments") or "{}"
            try:
                args = json.loads(args_raw)
            except (TypeError, ValueError):
                args = {"_raw": args_raw}
            out.append({"tool": d.get("name") or "unknown", "args": args,
                        "callId": d.get("callId"), "isError": False, "error": None})
        elif rtype == "tool/result":
            d = rec.get("data") or {}
            blocks = ((d.get("message") or {}).get("content") or [])
            for blk in blocks:
                if isinstance(blk, dict) and blk.get("type") == "tool-result":
                    for st in out:
                        if st.get("callId") == blk.get("toolCallId"):
                            st["isError"] = bool(blk.get("isError"))
                            if blk.get("isError"):
                                st["error"] = str(blk.get("content"))[:300]
                            break
        return out

    # -- 框架接口 -----------------------------------------------------------

    def run(self, instance: TaskInstance, env: Env) -> Trajectory:
        cwd = env.cwd
        result = self._call_cli(cwd, instance.instruction)

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
