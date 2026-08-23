import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_eval.datasets.capabilities import list_base_templates
from agent_eval.datasets.templates import instantiate
from agent_eval.datasets.verifier import verify
from agent_eval.core import Trajectory


def _inst(capability, seed=7):
    tmpl = next(t for t in list_base_templates() if t.capability == capability)
    return instantiate(tmpl, seed=seed)


def test_tool_call_correct_passes():
    inst = _inst("tool_call")
    r = verify(inst, {"contacts": {"Alice": {"phone": inst.params["PHONE"]}}}, Trajectory())
    assert r.passed is True, r


def test_tool_call_incomplete_fails_ftp():
    inst = _inst("tool_call")
    r = verify(inst, {"contacts": {"Alice": {"phone": "00000000000"}}}, Trajectory())
    assert r.passed is False
    assert r.fail_to_pass["phone_updated"] is False


def test_tool_call_surface_complete_fails_ptp():
    inst = _inst("tool_call")
    r = verify(inst, {"contacts": {"Alice": {"phone": inst.params["PHONE"]}, "Z": {}}}, Trajectory())
    assert r.passed is False
    assert r.pass_to_pass["no_extra_contact"] is False
