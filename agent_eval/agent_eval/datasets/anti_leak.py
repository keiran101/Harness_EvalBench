"""Anti-leak defenses for the evaluation dataset (design doc §7.7, spec §6 — red line).

Four mechanisms:
  1. Random instance parameters  -> handled in templates.instantiate (seeds differ)
  2. canary GUID                -> model outputting it proves contamination
  3. time freshness            -> prefer scenarios dated after the model's cutoff
  4. isolation red line        -> the *construct* (setup generator) is reusable, but the
                                  concrete instantiated questions must never enter training
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any

from .templates import TaskTemplate


def make_canary() -> str:
    return f"CANARY-{uuid.uuid4().hex}"


def inject_canary(text: str, canary: str) -> str:
    return f"{text}\n[system-note:{canary}]"


def is_leaked(text: str, canary: str) -> bool:
    return canary in text


def fresh_after(cutoff: str) -> str:
    """Return an ISO date strictly after the model's training cutoff."""
    d = datetime.date.fromisoformat(cutoff)
    return (d + datetime.timedelta(days=1)).isoformat()


def mark_isolation(template: TaskTemplate) -> TaskTemplate:
    template.leak_guard["isolation"] = True
    return template


def wire_leak_guard(template: TaskTemplate, cutoff: str = "2026-07-01",
                    inject: bool = True) -> TaskTemplate:
    """Populate a template's leak_guard with the full red-line set (spec §6):

    - canary GUID, also embedded into the instruction as a tripwire: if a model ever
      echoes it, that proves contamination (spec: canary GUID);
    - freshness: prefer instances dated after the model's training cutoff;
    - isolation marker: the template (construct) is reusable, instances must not enter
      training data.
    """
    canary = make_canary()
    template.leak_guard["canary"] = canary
    template.leak_guard["fresh_after"] = fresh_after(cutoff)
    template.leak_guard["isolation"] = True
    if inject:
        template.instruction = inject_canary(template.instruction, canary)
    return template
