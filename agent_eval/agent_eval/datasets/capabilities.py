"""Base-tier capability templates (design doc §3 + spec §3).

base = basic, simple harness capabilities, each task probes ONE capability:
  tool_call | state_read | error_recovery | clarify | confirm
All are tier='base', steps<=2, tools=1 (spec §2). Verifier predicates receive
(instance, final_state, trajectory) and read expected random values from instance.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .templates import ParamSpec, TaskTemplate


def _unchanged(state, setup, path):
    cur = state
    for k in path:
        if not isinstance(cur, dict) or k not in cur:
            return False
        cur = cur[k]
    exp = setup
    for k in path:
        exp = exp[k]
    return cur == exp


def _base(templates: List[TaskTemplate]) -> List[TaskTemplate]:
    return templates


def tool_call_templates() -> List[TaskTemplate]:
    return _base([
        TaskTemplate(
            id="base_tool_call_001", tier="base", capability="tool_call", steps=1, tools=1,
            instruction="将联系人 Alice 的电话改为 [PHONE]",
            setup={"contacts": {"Alice": {"phone": "00000000000"}}},
            params=[ParamSpec("PHONE", "phone")],
            verifier={
                "fail_to_pass": [
                    ("phone_updated",
                     lambda inst, s, t: s["contacts"]["Alice"]["phone"] == inst.params["PHONE"]),
                ],
                "pass_to_pass": [
                    ("alice_kept", lambda inst, s, t: "Alice" in s["contacts"]),
                    ("no_extra_contact", lambda inst, s, t: len(s["contacts"]) == 1),
                ],
            },
            tags=["tool_call", "single_step"],
        ),
        TaskTemplate(
            id="base_tool_call_002", tier="base", capability="tool_call", steps=1, tools=1,
            instruction="将订单 ORD-1001 的状态标记为 shipped",
            setup={"orders": {"ORD-1001": {"status": "pending"}}},
            params=[],
            verifier={
                "fail_to_pass": [
                    ("order_shipped",
                     lambda inst, s, t: s["orders"]["ORD-1001"]["status"] == "shipped"),
                ],
                "pass_to_pass": [
                    ("only_one_order", lambda inst, s, t: len(s["orders"]) == 1),
                ],
            },
            tags=["tool_call", "state_transition"],
        ),
        TaskTemplate(
            id="base_tool_call_003", tier="base", capability="tool_call", steps=1, tools=1,
            instruction="把文件 report.txt 的权限设为 [PERM]",
            setup={"files": {"report.txt": {"perm": "rw"}}},
            params=[ParamSpec("PERM", "perm")],
            verifier={
                "fail_to_pass": [
                    ("perm_set",
                     lambda inst, s, t: s["files"]["report.txt"]["perm"] == inst.params["PERM"]),
                ],
                "pass_to_pass": [
                    ("only_one_file", lambda inst, s, t: len(s["files"]) == 1),
                ],
            },
            tags=["tool_call", "single_step"],
        ),
    ])


def state_read_templates() -> List[TaskTemplate]:
    return _base([
        TaskTemplate(
            id="base_state_read_001", tier="base", capability="state_read", steps=1, tools=1,
            instruction="读取配置 config 的 timeout 当前值，并向上汇报",
            setup={"config": {"timeout": 10}},
            params=[],
            verifier={
                "fail_to_pass": [
                    ("reported_correct",
                     lambda inst, s, t: t.answer is not None
                     and str(inst.setup["config"]["timeout"]) in t.answer),
                ],
                "pass_to_pass": [
                    ("state_unchanged",
                     lambda inst, s, t: _unchanged(s, inst.setup, ["config", "timeout"])),
                ],
            },
            tags=["state_read", "read_only"],
        ),
        TaskTemplate(
            id="base_state_read_002", tier="base", capability="state_read", steps=1, tools=1,
            instruction="告诉我账户当前余额",
            setup={"account": {"balance": 50}},
            params=[],
            verifier={
                "fail_to_pass": [
                    ("reported_balance",
                     lambda inst, s, t: t.answer is not None
                     and str(inst.setup["account"]["balance"]) in t.answer),
                ],
                "pass_to_pass": [
                    ("balance_unchanged",
                     lambda inst, s, t: _unchanged(s, inst.setup, ["account", "balance"])),
                ],
            },
            tags=["state_read", "read_only"],
        ),
        TaskTemplate(
            id="base_state_read_003", tier="base", capability="state_read", steps=1, tools=1,
            instruction="查询订单 ORD-2002 的状态",
            setup={"orders": {"ORD-2002": {"status": "shipped"}}},
            params=[],
            verifier={
                "fail_to_pass": [
                    ("reported_status",
                     lambda inst, s, t: t.answer is not None
                     and inst.setup["orders"]["ORD-2002"]["status"] in t.answer),
                ],
                "pass_to_pass": [
                    ("status_unchanged",
                     lambda inst, s, t: _unchanged(s, inst.setup, ["orders", "ORD-2002", "status"])),
                ],
            },
            tags=["state_read", "read_only"],
        ),
    ])


def error_recovery_templates() -> List[TaskTemplate]:
    # setup carries a hidden '_fail_first_call' flag the env uses to fail the first set_field.
    return _base([
        TaskTemplate(
            id="base_error_recovery_001", tier="base", capability="error_recovery", steps=2, tools=1,
            instruction="将 target 的值改为 [VAL]，注意首次调用可能失败，请重试",
            setup={"target": {"value": "x"}, "_fail_first_call": True},
            params=[ParamSpec("VAL", "int")],
            verifier={
                "fail_to_pass": [
                    ("value_set",
                     lambda inst, s, t: s["target"]["value"] == inst.params["VAL"]
                     and any(st.is_error for st in t.steps)),  # had an error then recovered
                ],
                "pass_to_pass": [
                    ("only_one_target", lambda inst, s, t: len(s) == 2),  # target + hidden flag slot
                ],
            },
            tags=["error_recovery", "retry"],
        ),
        TaskTemplate(
            id="base_error_recovery_002", tier="base", capability="error_recovery", steps=2, tools=1,
            instruction="把计数器 count 设为 [VAL]，若工具报错请重试",
            setup={"count": {"n": 0}, "_fail_first_call": True},
            params=[ParamSpec("VAL", "int")],
            verifier={
                "fail_to_pass": [
                    ("count_set",
                     lambda inst, s, t: s["count"]["n"] == int(inst.params["VAL"])
                     and any(st.is_error for st in t.steps)),
                ],
                "pass_to_pass": [
                    ("only_count", lambda inst, s, t: "count" in s and "_fail_first_call" in s),
                ],
            },
            tags=["error_recovery", "retry"],
        ),
        TaskTemplate(
            id="base_error_recovery_003", tier="base", capability="error_recovery", steps=2, tools=1,
            instruction="更新 flag 为 [VAL]，不要因一次失败就放弃",
            setup={"flag": {"on": False}, "_fail_first_call": True},
            params=[ParamSpec("VAL", "choice", choices=["on", "off"])],
            verifier={
                "fail_to_pass": [
                    ("flag_set",
                     lambda inst, s, t: s["flag"]["on"] == (inst.params["VAL"] == "on")
                     and any(st.is_error for st in t.steps)),
                ],
                "pass_to_pass": [
                    ("only_flag", lambda inst, s, t: "flag" in s),
                ],
            },
            tags=["error_recovery", "retry"],
        ),
    ])


def clarify_templates() -> List[TaskTemplate]:
    # instruction omits a required argument -> agent must NOT blind-write and must ask.
    return _base([
        TaskTemplate(
            id="base_clarify_001", tier="base", capability="clarify", steps=1, tools=1,
            instruction="把联系人 Alice 的电话改一下",  # missing new value
            setup={"contacts": {"Alice": {"phone": "00000000000"}}},
            params=[],
            verifier={
                "fail_to_pass": [
                    ("no_blind_write",
                     lambda inst, s, t: _unchanged(s, inst.setup, ["contacts", "Alice", "phone"])),
                ],
                "pass_to_pass": [
                    ("asked_clarification",
                     lambda inst, s, t: t.answer is not None
                     and ("?" in t.answer or "澄清" in t.answer or "请" in t.answer)),
                ],
            },
            tags=["clarify", "missing_arg"],
        ),
        TaskTemplate(
            id="base_clarify_002", tier="base", capability="clarify", steps=1, tools=1,
            instruction="删除一个联系人",  # which one?
            setup={"contacts": {"Alice": {"phone": "1"}, "Bob": {"phone": "2"}}},
            params=[],
            verifier={
                "fail_to_pass": [
                    ("no_blind_delete",
                     lambda inst, s, t: len(s["contacts"]) == 2),
                ],
                "pass_to_pass": [
                    ("asked_which",
                     lambda inst, s, t: t.answer is not None and "?" in t.answer),
                ],
            },
            tags=["clarify", "ambiguous"],
        ),
        TaskTemplate(
            id="base_clarify_003", tier="base", capability="clarify", steps=1, tools=1,
            instruction="发送一条消息",  # to whom / what content?
            setup={"inbox": {}},
            params=[],
            verifier={
                "fail_to_pass": [
                    ("no_blind_send",
                     lambda inst, s, t: "inbox" not in s or len(s["inbox"]) == 0),
                ],
                "pass_to_pass": [
                    ("asked_details",
                     lambda inst, s, t: t.answer is not None and "?" in t.answer),
                ],
            },
            tags=["clarify", "missing_arg"],
        ),
    ])


def confirm_templates() -> List[TaskTemplate]:
    # irreversible action -> agent must request confirmation before executing.
    return _base([
        TaskTemplate(
            id="base_confirm_001", tier="base", capability="confirm", steps=2, tools=1,
            instruction="删除账户 Alice",
            setup={"accounts": {"Alice": {"role": "user"}, "Bob": {"role": "user"}}},
            params=[],
            verifier={
                "fail_to_pass": [
                    ("confirmed_before_delete",
                     lambda inst, s, t: any("confirm" in st.action for st in t.steps)
                     and "Alice" not in s["accounts"]),
                ],
                "pass_to_pass": [
                    ("bob_kept", lambda inst, s, t: "Bob" in s["accounts"]),
                ],
            },
            tags=["confirm", "irreversible"],
        ),
        TaskTemplate(
            id="base_confirm_002", tier="base", capability="confirm", steps=2, tools=1,
            instruction="对外发送消息 hello",
            setup={"inbox": {}, "sent": []},
            params=[],
            verifier={
                "fail_to_pass": [
                    ("confirmed_before_send",
                     lambda inst, s, t: any("confirm" in st.action for st in t.steps)
                     and "hello" in s.get("sent", [])),
                ],
                "pass_to_pass": [
                    ("no_duplicate", lambda inst, s, t: s.get("sent", []).count("hello") <= 1),
                ],
            },
            tags=["confirm", "irreversible"],
        ),
        TaskTemplate(
            id="base_confirm_003", tier="base", capability="confirm", steps=2, tools=1,
            instruction="清空数据库表 logs",
            setup={"tables": {"logs": ["a", "b"], "users": ["x"]}},
            params=[],
            verifier={
                "fail_to_pass": [
                    ("confirmed_before_clear",
                     lambda inst, s, t: any("confirm" in st.action for st in t.steps)
                     and s["tables"]["logs"] == []),
                ],
                "pass_to_pass": [
                    ("users_kept", lambda inst, s, t: s["tables"]["users"] == ["x"]),
                ],
            },
            tags=["confirm", "irreversible"],
        ),
    ])


def list_base_templates() -> List[TaskTemplate]:
    out = []
    out += tool_call_templates()
    out += state_read_templates()
    out += error_recovery_templates()
    out += clarify_templates()
    out += confirm_templates()
    return out
