import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_eval.datasets.templates import (
    TaskTemplate, TaskInstance, ParamSpec, instantiate
)


def _tmpl():
    return TaskTemplate(
        id="base_tool_call_001", tier="base", capability="tool_call",
        steps=1, tools=1,
        instruction="将联系人 [NAME] 的电话改为 [PHONE]",
        setup={"contacts": {"PLACEHOLDER": {"phone": "000"}}},
        params=[ParamSpec("NAME", "name"), ParamSpec("PHONE", "phone")],
        verifier={"fail_to_pass": [], "pass_to_pass": []},
    )


def test_instantiate_fills_slots():
    inst = instantiate(_tmpl(), seed=1)
    assert "[NAME]" not in inst.instruction and "[PHONE]" not in inst.instruction
    assert inst.params["NAME"] and inst.params["PHONE"]


def test_instantiate_seed_diversity():
    a = instantiate(_tmpl(), seed=1).params["PHONE"]
    b = instantiate(_tmpl(), seed=2).params["PHONE"]
    assert a != b, "different seeds must yield different random params (anti-leak)"
