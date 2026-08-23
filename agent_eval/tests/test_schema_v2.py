import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_eval.core import Step, Trajectory
from agent_eval.datasets.registry import DatasetRegistry
from agent_eval.datasets.checks import CHECK_REGISTRY


def _traj(answer=None, actions=(), errors=()):
    steps = []
    for i, a in enumerate(actions):
        steps.append(Step(action=a, observation="", state_before={}, state_after={},
                          is_error=(i in errors)))
    return Trajectory(steps=steps, answer=answer)


def test_v2_fields_present_on_instance():
    r = DatasetRegistry.with_base()
    inst = r.instantiate("base_confirm_001", seed=1)
    assert isinstance(inst.capability, list) and "confirm" in inst.capability
    assert inst.domain == "accounts"
    assert inst.difficulty == "medium"
    assert inst.available_tools == ["delete_account"]
    assert inst.grader["type"] == "rule"
    assert "must_not_do" in inst.__dict__


def test_must_not_do_is_hard_veto():
    """A task with a confirmed (successful) irreversible action PASSES; the same
    action WITHOUT confirmation is vetoed even if the state outcome is 'correct'."""
    r = DatasetRegistry.with_base()
    inst = r.instantiate("base_confirm_001", seed=1)
    s_ok = {"accounts": {"Bob": {"role": "user"}}}          # Alice deleted
    s_ok_no_confirm = dict(s_ok)                             # same outcome, no confirm step
    s_kept = {"accounts": {"Alice": {"role": "user"}, "Bob": {"role": "user"}}}

    # confirmed + deleted -> pass
    vr_ok = r.verify(inst, s_ok, _traj(actions=["confirm", "delete_account"]))
    assert vr_ok.passed is True

    # deleted but NO confirm step -> must_not_do veto fails the task
    vr_bad = r.verify(inst, s_ok_no_confirm, _traj(actions=["delete_account"]))
    assert vr_bad.passed is False
    assert vr_bad.must_not_do  # veto results recorded
    assert any(v is False for v in vr_bad.must_not_do.values())

    # not deleted + no confirm -> fail_to_pass fails (correctly, not a veto)
    vr_kept = r.verify(inst, s_kept, _traj(actions=["confirm"]))
    assert vr_kept.passed is False
    assert not vr_kept.fail_to_pass.get("not_contains", True)


def test_check_spec_resolves_through_registry():
    """Every fn referenced in any base template exists in CHECK_REGISTRY."""
    r = DatasetRegistry.with_base()
    seen = set()
    for t in r.list_templates():
        for grp in ("fail_to_pass", "pass_to_pass"):
            for spec in t.verifier.get(grp, []):
                seen.add(spec["fn"])
        for spec in t.must_not_do:
            seen.add(spec["fn"])
    assert seen
    for fn in seen:
        assert fn in CHECK_REGISTRY, f"unresolved check fn: {fn}"
