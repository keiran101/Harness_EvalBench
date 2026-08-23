import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_eval.metrics.metrics import (
    pass_at_k, pass_k, pass_consecutive_k, summarize
)
from agent_eval.core import EvalReport


def test_pass_at_k():
    assert pass_at_k([True, False, True], 3) == 1.0
    assert pass_at_k([False, False, False], 3) == 0.0


def test_pass_k():
    assert pass_k([True, False, True], 3) == 2 / 3


def test_pass_consecutive_k():
    assert pass_consecutive_k([True, True, True], 3) == 1.0
    assert pass_consecutive_k([True, False, True], 3) == 0.0


def test_summarize_report_discipline():
    reps = [
        EvalReport(case_id="c1", tier="base", capability="tool_call", passed=True,
                   first_error_step=None, metrics={}),
        EvalReport(case_id="c2", tier="base", capability="tool_call", passed=False,
                   first_error_step=0, metrics={}),
    ]
    s = summarize(reps, k=2)
    assert s["k"] == 2
    assert s["sample_size"] == 2
    assert s["overall"]["pass_k"] == 0.5
    assert s["overall"]["first_error_cases"] == 1
    assert "tool_call" in s["by_capability"]
    assert "k_scope" in s and "env" in s
