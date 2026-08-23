import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_eval.core import (
    Step, Trajectory, EvalCase, VerificationResult, EvalReport, first_error_step
)


def test_first_error_step_finds_first():
    traj = Trajectory(steps=[
        Step(action="a", observation="ok", state_before={}, state_after={}, is_error=False),
        Step(action="b", observation="err", state_before={}, state_after={}, is_error=True, error_category="tool_fail"),
        Step(action="c", observation="err", state_before={}, state_after={}, is_error=True),
    ])
    assert first_error_step(traj) == 1


def test_first_error_step_none_when_clean():
    traj = Trajectory(steps=[
        Step(action="a", observation="ok", state_before={}, state_after={}, is_error=False),
    ])
    assert first_error_step(traj) is None


def test_verification_result_fields():
    vr = VerificationResult(passed=True, fail_to_pass={"x": True}, pass_to_pass={"y": True})
    assert vr.passed and vr.fail_to_pass["x"] and vr.pass_to_pass["y"]


def test_eval_report_carries_first_error():
    r = EvalReport(case_id="c1", tier="base", capability="tool_call", passed=True,
                   first_error_step=None, metrics={"pass": 1.0})
    assert r.first_error_step is None
