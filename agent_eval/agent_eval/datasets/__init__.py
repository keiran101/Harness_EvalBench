"""Dataset layer (design doc §7, spec §1.2)."""

from .templates import (
    ParamSpec,
    TaskInstance,
    TaskTemplate,
    instantiate,
)
from .capabilities import list_base_templates
from .verifier import verify
from .anti_leak import (
    make_canary, inject_canary, is_leaked, fresh_after, mark_isolation, wire_leak_guard,
)
from .registry import DatasetRegistry

__all__ = [
    "ParamSpec", "TaskInstance", "TaskTemplate", "instantiate",
    "list_base_templates", "verify",
    "make_canary", "inject_canary", "is_leaked", "fresh_after", "mark_isolation",
    "wire_leak_guard", "DatasetRegistry",
]
