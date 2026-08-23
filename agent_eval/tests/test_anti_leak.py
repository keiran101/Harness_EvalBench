import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_eval.datasets.anti_leak import (
    make_canary, inject_canary, is_leaked, fresh_after, mark_isolation
)
from agent_eval.datasets.templates import TaskTemplate


def test_canary_roundtrip():
    c = make_canary()
    text = inject_canary("do something", c)
    assert is_leaked(text, c) is True
    assert is_leaked("do something", c) is False


def test_fresh_after():
    assert fresh_after("2026-01-01") == "2026-01-02"


def test_mark_isolation_sets_flag():
    t = TaskTemplate(id="x", tier="base", capability="tool_call", steps=1, tools=1,
                     instruction="i", setup={}, params=[], verifier={})
    mark_isolation(t)
    assert t.leak_guard.get("isolation") is True
