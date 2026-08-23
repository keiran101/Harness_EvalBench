"""Deterministic verifier: FAIL_TO_PASS + PASS_TO_PASS dual check (design doc §7.4).

A task passes only when EVERY fail_to_pass check is True (the problem was really
solved, not by luck) AND every pass_to_pass check stays True (no new regression was
introduced). Binary reward, deterministic code — preferred over LLM-Judge when the
success condition is mechanically checkable (design doc §8.1).
"""

from __future__ import annotations

from typing import Any, Dict

from ..core import VerificationResult
from .templates import TaskInstance


def verify(instance: TaskInstance, final_state: Dict[str, Any], trajectory) -> VerificationResult:
    ftp: Dict[str, bool] = {}
    for name, fn in instance.verifier.get("fail_to_pass", []):
        try:
            ftp[name] = bool(fn(instance, final_state, trajectory))
        except Exception:
            ftp[name] = False

    ptp: Dict[str, bool] = {}
    for name, fn in instance.verifier.get("pass_to_pass", []):
        try:
            ptp[name] = bool(fn(instance, final_state, trajectory))
        except Exception:
            ptp[name] = False

    passed = bool(ftp) and all(ftp.values()) and all(ptp.values())
    return VerificationResult(passed=passed, fail_to_pass=ftp, pass_to_pass=ptp)
