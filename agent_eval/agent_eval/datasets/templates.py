"""Parametric task templates + instantiation.

A task is not a static string but an instantiable template (design doc §7.8). Each
random parameter is generated from a seed so that instances differ every run — this is
a primary anti-leak mechanism (can't replay a fixed sequence).

Schema (v2, aligned with external design review 2026-08-23)
-----------------------------------------------------------
TaskTemplate / TaskInstance fields:
  id, template_id        : stable identifier (instance appends __s<seed>)
  domain                 : business domain (calendar/finance/...); orthogonal to capability
  capability             : LIST of capabilities exercised (e.g. ["tool_use","multi_step"])
  tier                   : base | Middle | hard  (structural complexity: steps/tools)
  difficulty             : easy | medium | hard  (expected difficulty; orthogonal to tier)
  steps, tools           : structural metadata (drive tier assignment)
  instruction            : user prompt, may contain [PARAM] slots
  setup                  : initial environment state, may contain [PARAM] slots
  params                 : ParamSpec list (random generators)
  available_tools        : list of tool names this task exposes (limits agent surface)
  expected_outcome       : human-readable before/after summary (metadata)
  must_do                : list of check specs that SHOULD happen (soft; recorded, not gating)
  must_not_do            : list of check specs that are HARD VETOES (any fail => task fails)
  verifier               : {fail_to_pass:[...], pass_to_pass:[...]}  dual-check
  grader                 : {"type": "rule" | "llm" | "custom", ...}  self-describes scorer
  leak_guard             : canary / fresh_after / isolation (red line)
  tags                   : free-form tags
  expectation            : optional success criteria (e.g. regression reason)

A "check spec" is a serializable dict: {"fn": <registered name>, "args": {...}}.
The actual callable lives in CHECK_REGISTRY (code), so datasets stay pure data.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

# A verification check is a predicate over (instance, final_state, trajectory).
# Predicates receive the TaskInstance so they can read expected random values
# (anti-leak: the target value is only known at instantiate time).
CheckFn = Callable[[Any, Dict[str, Any], Any], bool]

# A serializable check spec used in files / templates.
CheckSpec = Dict[str, Any]  # {"fn": str, "args": dict}


@dataclass
class ParamSpec:
    name: str
    generator: str            # name | phone | int | date | order_id | email | choice
    choices: Optional[List[str]] = None


@dataclass
class TaskTemplate:
    id: str
    tier: str                 # base | Middle | hard
    instruction: str          # may contain [PARAM] slots
    setup: dict               # initial environment state (may contain [PARAM] slots)
    params: List[ParamSpec]
    # ---- v2 schema additions ----
    domain: str = "general"
    capability: List[str] = field(default_factory=list)
    difficulty: str = "easy"
    steps: int = 1
    tools: int = 1
    available_tools: List[str] = field(default_factory=list)
    expected_outcome: str = ""
    must_do: List[CheckSpec] = field(default_factory=list)
    must_not_do: List[CheckSpec] = field(default_factory=list)
    verifier: Dict[str, List[CheckSpec]] = field(default_factory=dict)
    grader: Dict[str, Any] = field(default_factory=lambda: {"type": "rule"})
    leak_guard: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    expectation: str = ""
    # ---- unified-env field (2026-08-23) ----
    # Names the storage backend for this template. May be empty -> defaults to
    # {"backend": "memory"}. Evaluator reads this to pick Env's backend; it never
    # splits evaluation by domain. Future domains add a backend value, not a new env.
    env: Dict[str, Any] = field(default_factory=lambda: {"backend": "memory"})
    # ---- reference-plan fields (2026-08-23) ----
    # Data-driven plans for real-agent harnesses (pi bridge). `reference_plan` is
    # the CORRECT tool-call sequence (args may hold [PARAM] placeholders, filled at
    # instantiate time); `reference_answer` is the agent's final text for read/report
    # tasks. May be empty -> the adapter falls back to no-op / empty answer.
    reference_plan: List[Dict[str, Any]] = field(default_factory=list)
    reference_answer: str = ""
    # ---- retrieval coverage (2026-08-24) ----
    # For info-gathering tasks on the disk backend: the set of relative file
    # paths the agent SHOULD read. Coverage = viewed ∩ gold_docs / gold_docs.
    gold_docs: List[str] = field(default_factory=list)


@dataclass
class TaskInstance:
    id: str
    template_id: str
    tier: str
    instruction: str
    setup: dict
    params: Dict[str, str]
    # ---- v2 schema additions ----
    domain: str = "general"
    capability: List[str] = field(default_factory=list)
    difficulty: str = "easy"
    steps: int = 1
    tools: int = 1
    available_tools: List[str] = field(default_factory=list)
    expected_outcome: str = ""
    must_do: List[CheckSpec] = field(default_factory=list)
    must_not_do: List[CheckSpec] = field(default_factory=list)
    verifier: Dict[str, List[CheckSpec]] = field(default_factory=dict)
    grader: Dict[str, Any] = field(default_factory=lambda: {"type": "rule"})
    leak_guard: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    expectation: str = ""
    # ---- unified-env field (2026-08-23) ----
    # Names the storage backend for this template. May be empty -> defaults to
    # {"backend": "memory"}. Evaluator reads this to pick Env's backend; it never
    # splits evaluation by domain. Future domains add a backend value, not a new env.
    env: Dict[str, Any] = field(default_factory=lambda: {"backend": "memory"})
    # ---- reference-plan fields (2026-08-23) ----
    # Data-driven plans for real-agent harnesses (pi bridge). `reference_plan` is
    # the CORRECT tool-call sequence (args may hold [PARAM] placeholders, filled at
    # instantiate time); `reference_answer` is the agent's final text for read/report
    # tasks. May be empty -> the adapter falls back to no-op / empty answer.
    reference_plan: List[Dict[str, Any]] = field(default_factory=list)
    reference_answer: str = ""
    # ---- retrieval coverage (2026-08-24) ----
    # For info-gathering tasks on the disk backend: the set of relative file
    # paths the agent SHOULD read. Coverage = viewed ∩ gold_docs / gold_docs.
    gold_docs: List[str] = field(default_factory=list)


_GENERATORS = {
    "name": lambda r: r.choice(["Alice", "Bob", "Carol", "Dave", "Eve", "Frank", "Grace"]),
    "phone": lambda r: f"13{r.randint(100000000, 999999999)}",
    "int": lambda r: str(r.randint(1, 999)),
    "date": lambda r: f"2026-{r.randint(1, 12):02d}-{r.randint(1, 28):02d}",
    "order_id": lambda r: f"ORD-{r.randint(10000, 99999)}",
    "email": lambda r: f"user{r.randint(1000, 9999)}@example.com",
    "perm": lambda r: r.choice(["r", "rx", "rwx"]),
}


def _gen(r: random.Random, spec: ParamSpec) -> str:
    if spec.generator == "choice":
        return str(r.choice(spec.choices or []))
    return str(_GENERATORS[spec.generator](r))


def _fill(text: str, params: Dict[str, str]) -> str:
    for k, v in params.items():
        text = text.replace(f"[{k}]", v).replace(f"{{{k}}}", v)
    return text


def _fill_setup(setup: dict, params: Dict[str, str]) -> dict:
    import json
    return json.loads(_fill(json.dumps(setup), params))


def _fill_check_args(args: dict, params: Dict[str, str]) -> dict:
    """Fill [PARAM] placeholders inside check-spec args (values/paths)."""
    out = {}
    for k, v in args.items():
        if isinstance(v, str):
            out[k] = _fill(v, params)
        elif isinstance(v, list):
            out[k] = [_fill(x, params) if isinstance(x, str) else x for x in v]
        else:
            out[k] = v
    return out


def _to_instance_fields(template: TaskTemplate, params: Dict[str, str],
                        instruction: str, setup: dict) -> dict:
    return dict(
        id=f"{template.id}__s{params.get('_seed_')}",
        template_id=template.id,
        tier=template.tier,
        instruction=instruction,
        setup=setup,
        params=params,
        domain=template.domain,
        capability=list(template.capability),
        difficulty=template.difficulty,
        steps=template.steps,
        tools=template.tools,
        available_tools=list(template.available_tools),
        expected_outcome=_fill(template.expected_outcome, params),
        must_do=[{**c, "args": _fill_check_args(c.get("args", {}), params)} for c in template.must_do],
        must_not_do=[{**c, "args": _fill_check_args(c.get("args", {}), params)} for c in template.must_not_do],
        verifier={
            k: [{**c, "args": _fill_check_args(c.get("args", {}), params)} for c in v]
            for k, v in template.verifier.items()
        },
        grader=dict(template.grader),
        leak_guard=dict(template.leak_guard),
        tags=list(template.tags),
        expectation=_fill(template.expectation, params),
        env=dict(template.env),
        reference_plan=[{**c, "args": _fill_check_args(c.get("args", {}), params)}
                        for c in template.reference_plan],
        reference_answer=_fill(template.reference_answer, params),
        gold_docs=[_fill(g, params) for g in (template.gold_docs or [])],
    )


def instantiate(template: TaskTemplate, seed: int) -> TaskInstance:
    r = random.Random(seed)
    params = {p.name: _gen(r, p) for p in template.params}
    instruction = _fill(template.instruction, params)
    setup = _fill_setup(template.setup, params)
    fields = _to_instance_fields(template, params, instruction, setup)
    fields["id"] = f"{template.id}__s{seed}"
    return TaskInstance(**fields)


def from_dict(d: dict) -> TaskTemplate:
    """Build a TaskTemplate from a serializable dict (file storage)."""
    params = [ParamSpec(**p) for p in d.get("params", [])]
    return TaskTemplate(
        id=d["id"],
        tier=d.get("tier", "base"),
        instruction=d["instruction"],
        setup=d["setup"],
        params=params,
        domain=d.get("domain", "general"),
        capability=d.get("capability", []),
        difficulty=d.get("difficulty", "easy"),
        steps=d.get("steps", 1),
        tools=d.get("tools", 1),
        available_tools=d.get("available_tools", []),
        expected_outcome=d.get("expected_outcome", ""),
        must_do=d.get("must_do", []),
        must_not_do=d.get("must_not_do", []),
        verifier=d.get("verifier", {}),
        grader=d.get("grader", {"type": "rule"}),
        leak_guard=d.get("leak_guard", {}),
        tags=d.get("tags", []),
        expectation=d.get("expectation", ""),
        env=d.get("env", {"backend": "memory"}),
        reference_plan=d.get("reference_plan", []),
        reference_answer=d.get("reference_answer", ""),
        gold_docs=d.get("gold_docs", []),
    )


def to_dict(t: TaskTemplate) -> dict:
    """Serialize a TaskTemplate to a dict (file storage)."""
    return {
        "id": t.id,
        "domain": t.domain,
        "capability": t.capability,
        "tier": t.tier,
        "difficulty": t.difficulty,
        "steps": t.steps,
        "tools": t.tools,
        "instruction": t.instruction,
        "setup": t.setup,
        "params": [{"name": p.name, "generator": p.generator,
                    **({"choices": p.choices} if p.choices else {})} for p in t.params],
        "available_tools": t.available_tools,
        "expected_outcome": t.expected_outcome,
        "must_do": t.must_do,
        "must_not_do": t.must_not_do,
        "verifier": t.verifier,
        "grader": t.grader,
        "leak_guard": t.leak_guard,
        "tags": t.tags,
        "expectation": t.expectation,
        "env": t.env,
        "reference_plan": t.reference_plan,
        "reference_answer": t.reference_answer,
        "gold_docs": t.gold_docs or [],
    }
