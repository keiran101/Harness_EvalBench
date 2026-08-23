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


def test_with_base_leak_guard_is_wired():
    """Red line (spec §6): leak_guard must be populated, canary embedded in instruction."""
    r = DatasetRegistry.with_base()
    inst = r.instantiate("base_tool_call_001", seed=1)
    lg = inst.leak_guard
    assert lg["canary"].startswith("CANARY-")
    assert lg["isolation"] is True
    assert "fresh_after" in lg
    assert lg["canary"] in inst.instruction          # tripwire visible to the model
    assert inst.expectation == ""                     # optional metadata defaults empty


def test_all_base_templates_leak_wired():
    r = DatasetRegistry.with_base()
    for t in r.list_templates():
        assert t.leak_guard.get("isolation") is True
        assert "canary" in t.leak_guard
        assert t.leak_guard["canary"] in t.instruction
