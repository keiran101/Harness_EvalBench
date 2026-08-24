import os
from agent_eval.core import Trajectory, Step


def _retrieval_data_dir():
    """Resolve the retrieval dataset dir relative to the installed package."""
    import agent_eval.datasets.templates as _t
    return os.path.join(os.path.dirname(os.path.dirname(_t.__file__)),
                        "data", "retrieval")


def test_trajectory_new_fields_default_none():
    t = Trajectory()
    assert t.latency_ms is None
    assert t.request_count is None
