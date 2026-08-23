import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_eval.observability.trace import Trace, detect_drift
from agent_eval.core import Trajectory, Step


def test_trace_node_error_rate():
    traj = Trajectory(steps=[
        Step(action="set", observation="err", state_before={}, state_after={}, is_error=True),
        Step(action="set", observation="ok", state_before={}, state_after={}, is_error=False),
    ])
    t = Trace().record_step(traj)
    assert t.node_error_rate() == 0.5


def test_drift_alert_and_short_history():
    hist = [1.0] * 10 + [0.1] * 10
    d = detect_drift(hist, window=10, drop=0.25)
    assert d["alert"] is True
    assert d["baseline"] == 1.0 and d["recent"] == 0.1

    assert detect_drift([1.0] * 5)["alert"] is False  # insufficient history
