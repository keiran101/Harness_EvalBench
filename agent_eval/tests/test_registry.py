import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_eval.datasets.registry import DatasetRegistry
from agent_eval.datasets.capabilities import list_base_templates


def _reg():
    r = DatasetRegistry(version="test")
    for t in list_base_templates():
        r.register(t)
    return r


def test_list_base_all():
    r = _reg()
    base = r.list_templates(tier="base")
    assert len(base) == 15
    assert all(t.tier == "base" for t in base)


def test_filter_by_capability():
    r = _reg()
    tc = r.list_templates(capability="tool_call")
    assert len(tc) == 3
    assert all(t.capability == "tool_call" for t in tc)


def test_instantiate_carries_leak_guard_and_diverse_seed():
    r = _reg()
    a = r.instantiate("base_tool_call_001", seed=1)
    b = r.instantiate("base_tool_call_001", seed=2)
    assert a.leak_guard == b.leak_guard
    # random phone param differs across seeds (anti-leak)
    assert a.params["PHONE"] != b.params["PHONE"]


def test_registry_with_base_helper():
    r = DatasetRegistry.with_base()
    assert len(r.list_templates()) == 15
