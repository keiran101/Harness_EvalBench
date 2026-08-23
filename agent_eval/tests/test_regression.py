import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_eval.closure.regression import RegressionStore
from agent_eval.core import Trajectory, Step
from agent_eval.datasets.templates import TaskInstance


def _inst():
    return TaskInstance(id="c1__s1", template_id="c1", tier="base", capability="confirm",
                        instruction="delete", setup={"accounts": {"A": {}}}, params={},
                        verifier={}, leak_guard={}, tags=[])


def test_regression_store_accumulates():
    store = RegressionStore()
    traj = Trajectory(steps=[Step(action="delete", observation="ok", state_before={},
                                  state_after={}, is_error=True)])
    store.add_badcase(_inst(), traj, reason="missing_confirm")
    store.add_badcase(_inst(), traj, reason="blind_write")
    assert len(store.list_regression()) == 2


def test_prefix_boundary_set():
    store = RegressionStore()
    traj = Trajectory(steps=[
        Step(action="read:phone", observation="10", state_before={}, state_after={}),
        Step(action="set:phone", observation="ok", state_before={}, state_after={}),
        Step(action="delete", observation="ok", state_before={}, state_after={}),
    ])
    store.add_badcase(_inst(), traj)
    boundary = store.prefix_boundary_set(2)
    assert len(boundary) == 1
    assert "read:phone" in boundary[0].instruction and "set:phone" in boundary[0].instruction
