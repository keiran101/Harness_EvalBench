"""Parametric task templates + instantiation.

A task is not a static string but an instantiable template (design doc §7.8). Each
random parameter is generated from a seed so that instances differ every run — this is
a primary anti-leak mechanism (can't replay a fixed sequence).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

# A verification check is a predicate over (instance, final_state, trajectory).
# Predicates receive the TaskInstance so they can read expected random values
# (anti-leak: the target value is only known at instantiate time).
CheckFn = Callable[[Any, Dict[str, Any], Any], bool]


@dataclass
class ParamSpec:
    name: str
    generator: str            # name | phone | int | date | order_id | email | choice
    choices: Optional[List[str]] = None


@dataclass
class TaskTemplate:
    id: str
    tier: str                 # base | Middle | hard
    capability: str
    steps: int
    tools: int
    instruction: str          # may contain [PARAM] slots
    setup: dict               # initial environment state (may contain [PARAM] slots)
    params: List[ParamSpec]
    verifier: Dict[str, List]  # {'fail_to_pass': [(name, CheckFn)], 'pass_to_pass': [...]}
    leak_guard: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)


@dataclass
class TaskInstance:
    id: str
    template_id: str
    tier: str
    capability: str
    instruction: str
    setup: dict
    params: Dict[str, str]
    verifier: Dict[str, List]
    leak_guard: Dict[str, Any]
    tags: List[str]


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
        text = text.replace(f"[{k}]", v)
    return text


def _fill_setup(setup: dict, params: Dict[str, str]) -> dict:
    import json
    return json.loads(_fill(json.dumps(setup), params))


def instantiate(template: TaskTemplate, seed: int) -> TaskInstance:
    r = random.Random(seed)
    params = {p.name: _gen(r, p) for p in template.params}
    instruction = _fill(template.instruction, params)
    setup = _fill_setup(template.setup, params)
    return TaskInstance(
        id=f"{template.id}__s{seed}",
        template_id=template.id,
        tier=template.tier,
        capability=template.capability,
        instruction=instruction,
        setup=setup,
        params=params,
        verifier=template.verifier,
        leak_guard=template.leak_guard,
        tags=template.tags,
    )
