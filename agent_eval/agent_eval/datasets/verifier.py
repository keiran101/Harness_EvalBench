"""Deterministic verifier: dual-check + hard-veto (design doc §7.4 / §8.2).

A task passes only when:
  - EVERY fail_to_pass check is True (the problem was really solved, not by luck)
  - EVERY pass_to_pass check stays True (no new regression introduced)
  - EVERY must_not_do check is True (HARD VETO — e.g. irreversible action without
    confirmation; any violation fails the task regardless of outcome)

Binary reward, deterministic code — preferred over LLM-Judge when the success
condition is mechanically checkable (design doc §8.1). Check specs are resolved
through CHECK_REGISTRY (datasets/checks.py) so dataset files stay pure data.
"""

from __future__ import annotations

from typing import Any, Dict

from ..core import VerificationResult
from .checks import bind
from .templates import TaskInstance


def _run(specs, instance, final_state, trajectory) -> Dict[str, bool]:
    out: Dict[str, bool] = {}
    for spec in specs:
        name = spec.get("fn", "?<unknown>")
        try:
            out[name] = bool(bind(spec)(instance, final_state, trajectory))
        except Exception:
            out[name] = False
    return out


def verify(instance: TaskInstance, final_state: Dict[str, Any], trajectory) -> VerificationResult:
    ftp = _run(instance.verifier.get("fail_to_pass", []), instance, final_state, trajectory)
    ptp = _run(instance.verifier.get("pass_to_pass", []), instance, final_state, trajectory)
    veto = _run(instance.must_not_do, instance, final_state, trajectory)

    passed = (
        (not ftp or all(ftp.values()))
        and (not ptp or all(ptp.values()))
        and (not veto or all(veto.values()))
    )
    return VerificationResult(
        passed=passed,
        fail_to_pass=ftp,
        pass_to_pass=ptp,
        must_not_do=veto,
    )
