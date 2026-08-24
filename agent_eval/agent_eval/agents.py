"""Example agents under test (design doc §6.6 model selection).

Deterministic *mock* agents that demonstrate the framework end-to-end with no LLM:
  - ReferenceAgent : always acts correctly (reads, retries, clarifies, confirms)
  - FlakyAgent     : correct but intermittently fails -> Pass@k high, Pass^k low
  - BuggyAgent     : makes an attributable first error (no confirm / wrong answer / gives up)
Swap `BaseAgent` for your real LLM agent to evaluate it.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from .core import Step, Trajectory
from .datasets.templates import TaskInstance
from .environments.tool_env import ToolCallingEnv, ToolError

# Harness knowledge: template_id -> (state path, random param name or None).
_PATHS = {
    "base_tool_call_001": (["contacts", "Alice", "phone"], "PHONE"),
    "base_tool_call_002": (["orders", "ORD-1001", "status"], None),  # fixed target: shipped
    "base_tool_call_003": (["files", "report.txt", "perm"], "PERM"),
    "base_state_read_001": (["config", "timeout"], None),
    "base_state_read_002": (["account", "balance"], None),
    "base_state_read_003": (["orders", "ORD-2002", "status"], None),
    "base_error_recovery_001": (["target", "value"], "VAL"),
    "base_error_recovery_002": (["count", "n"], "VAL"),
    "base_error_recovery_003": (["flag", "on"], "VAL"),
}

# Irreversible actions per confirm template: kind -> target
_DESTRUCTIVE = {
    "base_confirm_001": ("delete", ["accounts", "Alice"]),
    "base_confirm_002": ("send", "hello"),
    "base_confirm_003": ("clear", "logs"),
}


def _snap(env: ToolCallingEnv) -> dict:
    return env.get_state()


def _step(action: str, obs: str, before: dict, after: dict,
          is_error: bool = False, category: Optional[str] = None) -> Step:
    return Step(action=action, observation=obs, state_before=before, state_after=after,
                is_error=is_error, error_category=category)


class ReferenceAgent:
    def __init__(self, name: str = "reference"):
        self.name = name

    def run(self, instance: TaskInstance, env: ToolCallingEnv) -> Trajectory:
        traj = Trajectory()
        cap = instance.capability[0] if instance.capability else ""
        if cap == "tool_call":
            self._tool_call(instance, env, traj)
        elif cap == "state_read":
            self._state_read(instance, env, traj)
        elif cap == "error_recovery":
            self._error_recovery(instance, env, traj)
        elif cap == "clarify":
            traj.answer = "请问需要补充什么信息？"          # ask, do not blind-act
        elif cap == "confirm":
            self._confirm(instance, env, traj)
        return traj

    # -- capability handlers -------------------------------------------------

    def _tool_call(self, instance, env, traj):
        path, param = _PATHS[instance.template_id]
        value = instance.params[param] if param else "shipped"
        before = _snap(env)
        obs = env.call_tool("set", path=path, value=value)
        traj.steps.append(_step(f"set:{path[-1]}", obs, before, _snap(env)))
        traj.answer = "done"

    def _state_read(self, instance, env, traj):
        path, _ = _PATHS[instance.template_id]
        before = _snap(env)
        obs = env.call_tool("read", path=path)
        traj.steps.append(_step(f"read:{path[-1]}", obs, before, _snap(env)))
        traj.answer = f"当前值: {obs}"

    def _error_recovery(self, instance, env, traj):
        path, param = _PATHS[instance.template_id]
        value = instance.params[param]
        before = _snap(env)
        try:
            obs = env.call_tool("set", path=path, value=value)
            traj.steps.append(_step(f"set:{path[-1]}", obs, before, _snap(env)))
        except ToolError as e:
            traj.steps.append(_step(f"set:{path[-1]}", str(e), before, _snap(env),
                                    is_error=True, category="tool_fail"))
            before2 = _snap(env)
            obs = env.call_tool("set", path=path, value=value)   # retry
            traj.steps.append(_step(f"set:{path[-1]}(retry)", obs, before2, _snap(env)))
        traj.answer = "done"

    def _confirm(self, instance, env, traj):
        kind, target = _DESTRUCTIVE[instance.template_id]
        before = _snap(env)
        env.call_tool("confirm", reason=kind)
        traj.steps.append(_step(f"confirm:{kind}", "recorded", before, _snap(env)))
        before2 = _snap(env)
        if kind == "delete":
            obs = env.call_tool("delete", path=target)
        elif kind == "send":
            obs = env.call_tool("send", text=target)
        else:
            obs = env.call_tool("clear", table=target)
        traj.steps.append(_step(f"{kind}:{target}", obs, before2, _snap(env)))
        traj.answer = "done"


class FlakyAgent(ReferenceAgent):
    """Deterministically fails (fail_every-1) of each fail_every runs:
    exactly 1 success per fail_every runs -> Pass@k=1.0 but Pass^k=1/fail_every."""

    def __init__(self, fail_every: int = 4):
        super().__init__(name="flaky")
        self.fail_every = fail_every
        self._runs = 0

    def run(self, instance, env):
        self._runs += 1
        if self._runs % self.fail_every != 0:
            traj = Trajectory()
            traj.steps.append(_step("noop", "flaky failure", _snap(env), _snap(env),
                                    is_error=True, category="flaky_noop"))
            return traj
        return super().run(instance, env)


class BuggyAgent(ReferenceAgent):
    """Makes an attributable first error on confirm / state_read / clarify / error_recovery."""

    def __init__(self):
        super().__init__(name="buggy")

    def run(self, instance, env):
        cap = instance.capability[0] if instance.capability else ""
        traj = Trajectory()
        if cap == "confirm":
            kind, target = _DESTRUCTIVE[instance.template_id]
            before = _snap(env)
            if kind == "delete":
                obs = env.call_tool("delete", path=target)
            elif kind == "send":
                obs = env.call_tool("send", text=target)
            else:
                obs = env.call_tool("clear", table=target)
            traj.steps.append(_step(f"{kind}:{target} (skipped approval)", obs, before, _snap(env),
                                    is_error=True, category="missing_confirm"))
            traj.answer = "done"
        elif cap == "state_read":
            path, _ = _PATHS[instance.template_id]
            before = _snap(env)
            obs = env.call_tool("read", path=path)
            st = _step(f"read:{path[-1]}", obs, before, _snap(env),
                       is_error=True, category="wrong_answer")
            traj.steps.append(st)
            traj.answer = "我不知道"          # wrong answer -> reported_correct fails
        elif cap == "clarify":
            path, _ = (["contacts", "Alice", "phone"], None)   # blind write
            before = _snap(env)
            try:
                obs = env.call_tool("set", path=path, value="12345")
            except Exception as e:
                obs = str(e)
            traj.steps.append(_step("blind:set", obs, before, _snap(env),
                                    is_error=True, category="blind_write"))
            traj.answer = "done"
        elif cap == "error_recovery":
            path, param = _PATHS[instance.template_id]
            value = instance.params[param]
            before = _snap(env)
            try:
                env.call_tool("set", path=path, value=value)
            except ToolError as e:
                traj.steps.append(_step(f"set:{path[-1]}", str(e), before, _snap(env),
                                        is_error=True, category="tool_fail"))
                traj.steps.append(_step("give_up", "giving up after failure",
                                        _snap(env), _snap(env), is_error=True,
                                        category="gave_up"))
            traj.answer = None
        else:
            return super().run(instance, env)
        return traj


class UnifiedMockAgent:
    """Domain-agnostic perfect executor (unified Env era, 2026-08-23).

    Drives the env purely from the template's verifier + setup, so it works for any
    domain/backend without hard-coded template_id->path maps. It is a *mock* (knows
    the answer from the verifier); real agents will not have this luxury. Used by the
    official CLI (python -m agent_eval --agent mock) for in-process self-testing of
    the whole pipeline on memory-backed (business) AND disk-backed (coding) tasks.
    """

    def __init__(self, name: str = "unified-mock"):
        self.name = name

    def run(self, instance, env) -> Trajectory:
        import json as _json
        traj = Trajectory()
        caps = set(instance.capability)
        before = self._snap(env)

        # Clarify capability: ask, do NOT act (passes asked_clarification, no side effects)
        if "clarify" in caps:
            traj.answer = "请补充一下具体需求？"
            return traj

        # Confirm capability: request confirmation BEFORE the irreversible action.
        # memory backend has a real confirm tool; disk backend records the step only
        # (the verifier checks trajectory action prefix, not an env side-effect).
        if "confirm" in caps:
            if instance.env.get("backend") == "memory":
                env.call_tool("confirm", reason="human-review")
            traj.steps.append(self._step("confirm", "recorded", before, self._snap(env)))

        # Retrieval capability: read every gold doc, then report their contents
        # (coverage = 1 for the perfect mock; real agents may score lower).
        if "retrieval" in caps:
            for p in (instance.gold_docs or []):
                b = self._snap(env)
                obs = env.call_tool("read", path=p)
                traj.steps.append(self._step(f"read:{p}", obs, b, self._snap(env)))
            if instance.setup:
                traj.answer = " | ".join(str(v) for v in instance.setup.values())
            return traj

        # State-read / report capability: read then report the value
        if "state_read" in caps:
            for path in self._read_paths(instance):
                b = self._snap(env)
                obs = env.call_tool("read", path=path)
                traj.steps.append(self._step(f"read:{path}", obs, b, self._snap(env)))
            if instance.setup:
                traj.answer = "当前值: " + " | ".join(
                    str(v) for v in instance.setup.values()
                )
            return traj

        # Tool-call capability: satisfy each fail_to_pass check by driving the env
        if "tool_call" in caps:
            self._satisfy_checks(instance, env, traj)
            traj.answer = "done"
            return traj

        # Fallback: read-only no-op
        traj.answer = "done"
        return traj

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _snap(env):
        return env.get_state()

    @staticmethod
    def _step(action, obs, before, after, is_error=False, category=None):
        return Step(action=action, observation=obs, state_before=before,
                    state_after=after, is_error=is_error, error_category=category)

    def _read_paths(self, instance):
        """Paths the agent should read for a state_read task (best-effort).

        - disk backend : setup keys ARE file paths (str)
        - memory backend: pull the nested-dict path from verifier specs that read
          setup (reported_value.value_path / state_eq.path / state_unchanged.path)
        """
        if instance.env.get("backend") == "disk":
            # Only read SOURCE files already present in setup; targets the verifier
            # expects the agent to WRITE must not be read (they don't exist yet).
            return [k for k in instance.setup.keys()]
        # memory backend: read the setup path the verifier inspects
        paths = []
        for c in instance.verifier.get("fail_to_pass", []) + instance.verifier.get("pass_to_pass", []):
            if c.get("fn") in ("reported_value", "state_eq", "state_unchanged", "len_eq"):
                p = c.get("args", {}).get("value_path") or c.get("args", {}).get("path")
                if p and p not in paths:
                    paths.append(p)
        return paths

    def _satisfy_checks(self, instance, env, traj):
        """Drive the env so every fail_to_pass check becomes True."""
        import json as _json
        for c in instance.verifier.get("fail_to_pass", []):
            fn = c.get("fn")
            args = c.get("args", {})
            if fn == "file_content_eq":
                p, v = args["path"], args["value"]
                b = self._snap(env)
                env.call_tool("write", path=p, content=v)
                traj.steps.append(self._step(f"write:{p}", "ok", b, self._snap(env)))
            elif fn == "json_field_eq":
                p, field, v = args["path"], args["field"], args["value"]
                b = self._snap(env)
                cur = _json.loads(env.call_tool("read", path=p))
                cur[field] = self._coerce(v)
                env.call_tool("write", path=p, content=_json.dumps(cur, ensure_ascii=False))
                traj.steps.append(self._step(f"write:{p}({field})", "ok", b, self._snap(env)))
            elif fn == "file_not_exists":
                p = args["path"]
                b = self._snap(env)
                env.call_tool("bash", command=f"rm -f {p}")
                traj.steps.append(self._step(f"bash:rm {p}", "ok", b, self._snap(env)))
            elif fn == "file_exists":
                pass  # already present in setup; nothing to do
            elif fn in ("state_eq", "len_eq", "not_contains", "contains"):
                self._memory_set(instance, env, traj, c)
            elif fn == "irreversible_without_confirm":
                pass  # handled by the confirm pre-step above

    def _memory_set(self, instance, env, traj, c):
        """Business-domain (memory backend) checks: set the target path to its value.

        Mirrors a real agent's error recovery: a transient first-call failure (setup
        flag _fail_first_call) is retried once.
        """
        from .environments.tool_env import ToolError
        fn = c.get("fn")
        args = c.get("args", {})
        path = args.get("path")
        if not path:
            return
        value = args.get("value")
        b = self._snap(env)
        if fn == "state_eq":
            try:
                env.call_tool("set", path=path, value=value)
            except ToolError:
                b2 = self._snap(env)
                obs = env.call_tool("set", path=path, value=value)   # retry
                traj.steps.append(self._step(f"set:{path[-1]}(retry)", obs, b2, self._snap(env)))
                return
            traj.steps.append(self._step(f"set:{path[-1]}", "ok", b, self._snap(env)))
        elif fn in ("len_eq", "not_contains", "contains"):
            pass  # assertions, not state mutations

    @staticmethod
    def _coerce(v):
        if isinstance(v, (int, float, bool)):
            return v
        s = str(v)
        if s.lower() in ("true", "false"):
            return s.lower() == "true"
        try:
            return int(s)
        except (TypeError, ValueError):
            return v
