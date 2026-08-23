import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_eval.datasets.capabilities import list_base_templates


def test_base_five_classes():
    tmpls = list_base_templates()
    caps = {}
    for t in tmpls:
        caps.setdefault(t.capability, 0)
        caps[t.capability] += 1
    assert set(caps) == {"tool_call", "state_read", "error_recovery", "clarify", "confirm"}


def test_base_count_and_tier():
    tmpls = list_base_templates()
    for t in tmpls:
        assert t.tier == "base"
        assert t.steps <= 2, f"{t.id} steps={t.steps} > 2"
        assert t.tools == 1
    # each class >= 3 templates
    from collections import Counter
    c = Counter(t.capability for t in tmpls)
    for k, v in c.items():
        assert v >= 3, f"{k} has {v} < 3"
    assert len(tmpls) == 15
