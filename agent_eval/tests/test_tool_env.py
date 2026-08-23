import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_eval.environments.tool_env import ToolCallingEnv, ToolError


def test_reset_restores_clean_state():
    env = ToolCallingEnv({"contacts": {"Alice": {"phone": "0"}}})
    env.call_tool("set", path=["contacts", "Alice", "phone"], value="1391")
    assert env.get_state()["contacts"]["Alice"]["phone"] == "1391"
    env.reset()
    assert env.get_state() == {"contacts": {"Alice": {"phone": "0"}}}


def test_set_and_read_roundtrip():
    env = ToolCallingEnv({"config": {"timeout": 10}})
    obs = env.call_tool("read", path=["config", "timeout"])
    assert obs == "10"
    env.call_tool("set", path=["config", "timeout"], value="20")
    assert env.call_tool("read", path=["config", "timeout"]) == "20"


def test_unknown_tool_raises():
    env = ToolCallingEnv({})
    try:
        env.call_tool("nope")
        assert False, "should raise"
    except ToolError:
        pass


def test_fail_first_then_success():
    env = ToolCallingEnv({"target": {"value": "x"}, "_fail_first_call": True})
    try:
        env.call_tool("set", path=["target", "value"], value="5")
        assert False, "first call should fail"
    except ToolError:
        pass
    assert env.call_tool("set", path=["target", "value"], value="5") == "ok"
    assert env.get_state()["target"]["value"] == "5"  # str field stays str
