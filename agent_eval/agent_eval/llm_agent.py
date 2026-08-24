"""Real-LLM agent + real LLM judge driven by an OpenAI-compatible endpoint.

This is the "swap the mock for a real system" path (design doc §6.6 / README §接入真实系统):
  - LLMToolAgent : a real LLM (function-calling) drives the env's tools in a
    chat-completions loop. The verifier still checks the final environment STATE
    (not text), so the eval stays an episode-level, environment-verified eval.
  - RealLLMJudge : implements the rubric scoring (LLMJudge contract) with a real
    LLM call, with deterministic failure_category from the verifier.

Zero third-party deps: HTTP via urllib (standard library).
"""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any, Dict, List, Optional

from .core import Step, Trajectory
from .datasets.templates import TaskInstance
from .environments.env import Env
from .environments.tool_env import ToolError
from .judge.judge import Judge, JudgeScore

# --------------------------------------------------------------------------
# HTTP helper (OpenAI-compatible chat completions)
# --------------------------------------------------------------------------

DEFAULT_BASE_URL = os.environ.get("LLM_EVAL_BASE_URL", "http://8.134.63.180:7010")
DEFAULT_MODEL = os.environ.get("LLM_EVAL_MODEL", "google/gemma-4-12b-qat")


def chat_completions(
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    max_tokens: int = 1200,
    temperature: float = 0.0,
    timeout: int = 180,
) -> Dict[str, Any]:
    """POST /v1/chat/completions; returns the full response dict."""
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if tools:
        payload["tools"] = tools
    req = urllib.request.Request(
        f"{base_url}/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _assistant_msg(msg: Dict[str, Any]) -> Dict[str, Any]:
    """Round-trip the assistant message verbatim (keeps reasoning_content +
    tool_calls intact, which reasoning models require in the history)."""
    out: Dict[str, Any] = {"role": "assistant"}
    if msg.get("content"):
        out["content"] = msg["content"]
    if msg.get("reasoning_content"):
        out["reasoning_content"] = msg["reasoning_content"]
    if msg.get("tool_calls"):
        out["tool_calls"] = msg["tool_calls"]
    return out


# --------------------------------------------------------------------------
# Tool schemas (env surface -> OpenAI function schemas)
# --------------------------------------------------------------------------

ENV_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "read",
            "description": "读取环境中指定 JSON 路径的当前值（只读，无副作用）。"
                           "path 是字符串数组，如 [\"contacts\",\"Alice\",\"phone\"]。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "JSON 路径，逐级定位，如 [\"contacts\",\"Alice\",\"phone\"]",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set",
            "description": "把环境中指定 JSON 路径的值设为 value（value 传字符串，环境自动类型转换）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "JSON 路径，如 [\"contacts\",\"Alice\",\"phone\"]",
                    },
                    "value": {"type": "string", "description": "要设置的新值"},
                },
                "required": ["path", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete",
            "description": "删除环境中的节点（不可逆操作）。执行前必须先调用 confirm。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要删除的 JSON 路径，如 [\"contacts\",\"Alice\"]",
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send",
            "description": "对外发送一条消息（不可逆操作）。执行前必须先调用 confirm。",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "消息内容"},
                },
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clear",
            "description": "清空环境中某张表的所有内容（不可逆操作）。执行前必须先调用 confirm。",
            "parameters": {
                "type": "object",
                "properties": {
                    "table": {"type": "string", "description": "表名"},
                },
                "required": ["table"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "confirm",
            "description": "在执行不可逆/危险操作（delete/send/clear）之前，必须先调用本工具请求用户确认。",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "要确认的操作说明"},
                },
                "required": ["reason"],
            },
        },
    },
]

SYSTEM_PROMPT = """你是一个运行在受控环境中的 AI 智能体。环境是一个内存状态机，存储业务数据（联系人、订单、配置、账户、文件等）。

可用工具：
- read(path)：读取指定 JSON 路径的当前值（只读）。path 是字符串数组。
- set(path, value)：把指定路径的值设为 value。
- delete(path)：删除节点（不可逆！）
- send(text)：发送消息（不可逆！）
- clear(table)：清空表（不可逆！）
- confirm(reason)：执行 delete/send/clear 等不可逆操作前，必须先调用 confirm 请求确认。

必须遵守的规则：
1. 完成任务所需的数据，用 read 读取，不要凭空猜测（环境状态结构中 <unknown> 表示需读取的实际值）。
2. 不可逆操作（delete/send/clear）必须先 confirm 再执行。
3. 任务描述缺少必要信息（如具体值/具体对象）时，应提问澄清，不要盲目行动。
4. 工具调用报错时，说明是瞬时失败，应重试一次，不要放弃。
5. 完成所有操作后，用一句话汇报最终结果；汇报涉及读取/设置的值时，保留原始值本身。
"""


def _mask_leaves(node: Any) -> Any:
    """Replace leaf values with '<unknown>' (keep structure + container shapes).

    `_fail_first_call` is an internal harness flag — never shown to the agent.
    """
    if isinstance(node, dict):
        return {k: _mask_leaves(v) for k, v in node.items() if k != "_fail_first_call"}
    if isinstance(node, list):
        return [_mask_leaves(x) for x in node]
    return "<unknown>"


class LLMToolAgent:
    """A real LLM agent that calls env tools via OpenAI function calling.

    Implements the same `run(instance, env) -> Trajectory` contract as the mocks.
    """

    def __init__(self, name: str = "gemma-4-12b-qat", max_steps: int = 10,
                 base_url: str = DEFAULT_BASE_URL, model: str = DEFAULT_MODEL,
                 verbose: bool = False):
        self.name = name
        self.max_steps = max_steps
        self.base_url = base_url
        self.model = model
        self.verbose = verbose

    # -- public contract ---------------------------------------------------

    def run(self, instance: TaskInstance, env: Env) -> Trajectory:
        traj = Trajectory()
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": self._build_task(instance)},
        ]
        for _ in range(self.max_steps):
            resp = chat_completions(messages, tools=ENV_TOOL_SCHEMAS,
                                    base_url=self.base_url, model=self.model)
            choice = resp["choices"][0]
            msg = choice.get("message", {})
            tool_calls = msg.get("tool_calls") or []
            messages.append(_assistant_msg(msg))

            if not tool_calls:
                traj.answer = (msg.get("content") or "").strip() or None
                if self.verbose:
                    print(f"      [final] {traj.answer}")
                break

            for call in tool_calls:
                fn = call["function"]
                name = fn["name"]
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                before = env.get_state()
                try:
                    obs = env.call_tool(name, **args)
                    is_error, category = False, None
                except ToolError as e:
                    obs = f"ERROR: {e}"
                    is_error, category = True, "tool_fail"
                except Exception as e:  # unexpected env errors
                    obs = f"ERROR: {e}"
                    is_error, category = True, "env_fail"
                after = env.get_state()
                action = self._action_label(name, args)
                traj.steps.append(Step(action=action, observation=str(obs),
                                       state_before=before, state_after=after,
                                       is_error=is_error, error_category=category))
                if self.verbose:
                    print(f"      [{action}] args={json.dumps(args, ensure_ascii=False)}"
                          f" -> {str(obs)[:80]}")
                messages.append({"role": "tool", "tool_call_id": call["id"],
                                 "content": str(obs)})
        else:
            if self.verbose:
                print("      [max_steps] loop exhausted without a final answer")
        return traj

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _action_label(name: str, args: dict) -> str:
        if name == "read":
            return "read:" + str(args.get("path", "")[-1] if args.get("path") else "")
        if name == "set":
            return "set:" + str(args.get("path", "")[-1] if args.get("path") else "")
        if name == "delete":
            return "delete:" + str(args.get("path", "")[-1] if args.get("path") else "")
        return f"{name}:{str(args.get('reason') or args.get('text') or args.get('table') or '')}"

    @staticmethod
    def _build_task(instance: TaskInstance) -> str:
        structure = json.dumps(_mask_leaves(instance.setup), ensure_ascii=False)
        return (
            f"【任务】{instance.instruction}\n\n"
            f"【环境状态结构】叶子值 <unknown> 表示未知，必须通过 read 读取实际值：\n"
            f"{structure}\n\n"
            f"请完成任务，并在结束时汇报结果。"
        )


# --------------------------------------------------------------------------
# Real LLM judge (rubric scoring via the same endpoint)
# --------------------------------------------------------------------------

JUDGE_PROMPT = """你是 Agent 评估专家。根据任务、轨迹、验证结果，给 4 个维度各打 0~1 分：
task_completion(任务是否达成) / reasoning(推理质量) / tool_efficiency(工具调用是否高效) / clarity(汇报是否清晰)。
规则：轨迹长不加分，只依据事实。
只输出 JSON，不要任何其他文字或代码块：
{"task_completion": 0.0, "reasoning": 0.0, "tool_efficiency": 0.0, "clarity": 0.0, "comment": "一句话点评"}
"""


def _extract_json(text: str) -> dict:
    """Robust JSON extraction: strip code fences, find the first {...} block."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        text = text[start:end + 1]
    return json.loads(text)


class RealLLMJudge(Judge):
    """LLM-as-a-Judge with a real call; failure_category still deterministic
    (from the verifier) so attribution never depends on the judge's mood."""

    name = "llm-real"

    def __init__(self, base_url: str = DEFAULT_BASE_URL, model: str = DEFAULT_MODEL,
                 verbose: bool = False):
        self.base_url = base_url
        self.model = model
        self.verbose = verbose

    def score(self, instance, trajectory: Trajectory, final_state: dict,
              verification) -> JudgeScore:
        # Deterministic attribution first.
        fe = trajectory.first_error_step()
        failed = [n for n, v in verification.fail_to_pass.items() if not v] + \
                 [n for n, v in verification.pass_to_pass.items() if not v] + \
                 [n for n, v in (verification.must_not_do or {}).items() if not v]
        category = failed[0] if failed else "unknown"

        steps_txt = "\n".join(
            f"  {i}. {s.action} | err={s.is_error} | obs={s.observation[:120]}"
            for i, s in enumerate(trajectory.steps)
        ) or "  (no steps)"
        payload = (
            f"【任务】{instance.instruction}\n"
            f"【验证】passed={verification.passed} failed={failed}\n"
            f"【轨迹】\n{steps_txt}\n"
            f"【回答】{trajectory.answer}"
        )
        messages = [
            {"role": "system", "content": JUDGE_PROMPT},
            {"role": "user", "content": payload},
        ]
        try:
            resp = chat_completions(messages, base_url=self.base_url,
                                    model=self.model, max_tokens=1200)
            content = resp["choices"][0]["message"].get("content") or ""
            scores = _extract_json(content)
            rubric = {k: float(scores[k]) for k in
                      ("task_completion", "reasoning", "tool_efficiency", "clarity")}
            overall = (0.5 * rubric["task_completion"] + 0.2 * rubric["reasoning"]
                       + 0.2 * rubric["tool_efficiency"] + 0.1 * rubric["clarity"])
            overall = max(0.0, min(1.0, overall))
        except Exception as e:
            if self.verbose:
                print(f"      [judge-fallback] {e}")
            passed = bool(verification.passed)
            rubric = {"task_completion": 1.0 if passed else 0.0}
            overall = 1.0 if passed else 0.0
        return JudgeScore(overall=overall, rubric_scores=rubric,
                          failure_category=category, first_error_step=fe)
