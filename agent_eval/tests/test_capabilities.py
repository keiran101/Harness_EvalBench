import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_eval.datasets.capabilities import list_base_templates
from collections import Counter


def test_base_five_classes():
    tmpls = list_base_templates()
    caps = set()
    for t in tmpls:
        caps.update(t.capability)
    assert caps == {"tool_call", "state_read", "error_recovery", "clarify", "confirm"}


def test_base_count_and_tier():
    tmpls = list_base_templates()
    for t in tmpls:
        assert t.tier == "base"
        assert t.steps <= 2, f"{t.id} steps={t.steps} > 2"
        assert t.tools == 1
        # v2 schema: capability is a list, domain + difficulty present
        assert isinstance(t.capability, list) and t.capability
        assert t.domain and t.domain != "general"
        assert t.difficulty in ("easy", "medium", "hard")
        assert t.available_tools  # tool surface is declared
        assert t.grader.get("type") == "rule"
    c = Counter(tuple(t.capability) for t in tmpls)
    for k, v in c.items():
        assert v >= 3, f"{k} has {v} < 3"
    assert len(tmpls) == 15
