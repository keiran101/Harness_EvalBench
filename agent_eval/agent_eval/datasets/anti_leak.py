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
