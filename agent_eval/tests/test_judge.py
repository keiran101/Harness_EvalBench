import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_eval.judge.judge import DummyJudge, LLMJudge, JudgeScore
from agent_eval.core import Trajectory, Step, VerificationResult


def _traj_with_error():
    return Trajectory(steps=[
        Step(action="set", observation="err", state_before={}, state_after={},
             is_error=True, error_category="tool_fail"),
        Step(action="set", observation="ok", state_before={}, state_after={}, is_error=False),
    ])


def test_dummy_judge_pass():
    vr = VerificationResult(passed=True, fail_to_pass={"x": True}, pass_to_pass={"y": True})
    s = DummyJudge().score(None, Trajectory(), {}, vr)
    assert s.overall == 1.0
    assert s.failure_category is None


def test_dummy_judge_fail_with_attribution():
    vr = VerificationResult(passed=False, fail_to_pass={"phone_updated": False},
                            pass_to_pass={"alice_kept": True})
    s = DummyJudge().score(None, _traj_with_error(), {}, vr)
    assert s.overall == 0.0
    assert s.failure_category == "phone_updated"
    assert s.first_error_step == 0


def test_llm_judge_requires_key():
    try:
        LLMJudge().score(None, Trajectory(), {}, VerificationResult(True, {}, {}))
        assert False, "should raise NotImplementedError"
    except NotImplementedError:
        pass
