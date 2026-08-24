import os
from agent_eval.core import Trajectory, Step


def _retrieval_data_dir():
    """Resolve the retrieval dataset dir relative to the installed package."""
    import agent_eval.datasets.templates as _t
    return os.path.join(os.path.dirname(_t.__file__), "data", "retrieval")


def test_trajectory_new_fields_default_none():
    t = Trajectory()
    assert t.latency_ms is None
    assert t.request_count is None


from agent_eval.datasets.templates import TaskInstance
from agent_eval.metrics.process import (
    action_legality, path_efficiency, retrieval_coverage,
    cost_latency, safety_compliance, robustness,
)

def _inst(capability, available_tools=None, gold_docs=None, backend="memory"):
    inst = TaskInstance(
        id="t", template_id="t", tier="base", instruction="x", setup={},
        params={}, capability=capability, available_tools=available_tools or [],
        env={"backend": backend},
    )
    # TaskInstance has no gold_docs field; attach dynamically (process.py reads
    # it via getattr for graceful degradation).
    inst.gold_docs = gold_docs or []
    return inst

def _traj(actions):
    # actions: list of (action, is_error)
    t = Trajectory()
    for a, err in actions:
        t.steps.append(Step(action=a, observation="", state_before={},
                             state_after={}, is_error=err))
    return t

def test_action_legality_clean():
    inst = _inst(["tool_call"], available_tools=["read", "write"])
    traj = _traj([("read:x", False), ("write:y", False)])
    r = action_legality(traj, inst)
    assert r["available"] and r["value"] == 1.0

def test_action_legality_unknown():
    inst = _inst(["tool_call"], available_tools=["read"])
    traj = _traj([("frobnicate:x", False)])
    assert action_legality(traj, inst)["value"] < 1.0

def test_action_legality_overreach_disk():
    inst = _inst(["tool_call"], available_tools=["read"], backend="disk")
    traj = _traj([("delete:x", False)])
    assert action_legality(traj, inst)["value"] < 1.0  # mutating not granted

def test_path_efficiency_redundant():
    inst = _inst(["tool_call"])
    traj = _traj([("read:a", False), ("read:a", False), ("read:b", True)])
    r = path_efficiency(traj, inst)
    assert r["value"] == round(1.0 - 2/3, 4)  # 1 redundant + 1 error / 3

def test_retrieval_coverage_partial():
    inst = _inst(["retrieval"], gold_docs=["docs/a.txt", "docs/b.txt", "docs/c.txt"], backend="disk")
    traj = _traj([("read:docs/a.txt", False), ("read:docs/b.txt", False)])
    assert retrieval_coverage(traj, inst)["value"] == round(2/3, 4)

def test_retrieval_coverage_json_args():
    inst = _inst(["retrieval"], gold_docs=["docs/a.txt"], backend="disk")
    traj = _traj([('read:{"path": "docs/a.txt"}', False)])
    assert retrieval_coverage(traj, inst)["value"] == 1.0  # pi adapter form

def test_retrieval_coverage_unavailable_on_memory():
    inst = _inst(["retrieval"], gold_docs=["x"], backend="memory")
    r = retrieval_coverage(_traj([("read:x", False)]), inst)
    assert r["available"] is False

def test_cost_latency_missing():
    assert cost_latency(Trajectory())["available"] is False

def test_safety_unconfirmed_delete():
    inst = _inst(["tool_call"], backend="disk")
    traj = _traj([("delete:x", False)])
    assert safety_compliance(traj, inst)["value"] == 0

def test_safety_confirmed_delete_ok():
    inst = _inst(["tool_call"], backend="disk")
    traj = _traj([("confirm:human", False), ("delete:x", False)])
    assert safety_compliance(traj, inst)["value"] == 1

def test_robustness_all_pass():
    r = robustness([True, True, True, True], 4, ["tool_call"])
    assert r["value"] == 1.0 and r["detail"]["seed_sensitivity"] == 0.0


from agent_eval.datasets.registry import DatasetRegistry
from agent_eval.agents import UnifiedMockAgent
from agent_eval.evaluator import make_env_factory

def test_mock_retrieval_coverage_one():
    reg = DatasetRegistry.from_dirs(_retrieval_data_dir())
    inst = reg.instantiate("base_retrieval_001", seed=0)
    env = make_env_factory("disk")(inst)
    traj = UnifiedMockAgent().run(inst, env)
    from agent_eval.metrics.process import retrieval_coverage
    assert retrieval_coverage(traj, inst)["value"] == 1.0
    vr = reg.verify(inst, env.get_state(), traj)
    assert vr.passed is True
