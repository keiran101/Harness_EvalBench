# -*- coding: utf-8 -*-
"""对 eval_pi_llm_retrieval_20260825_001329.json 用【修复后的度量】重验。

忠实重建：final_state 由 setup + 轨迹里的写/改/删/bash(cp/rm/mv) 回放得到，
再调用框架真实 verify()。gold_docs 用运行当时数据集(git cc35911: 改名前)。
"""
import sys, json, subprocess, re
sys.path.insert(0, "agent_eval")
from agent_eval.core import Trajectory, Step
from agent_eval.datasets.verifier import verify
from agent_eval.metrics.process import (
    _tool_of, _read_path, _norm_path, _bash_read_paths, READ_TOOLS,
)

RESULT = "results/eval_pi_llm_retrieval_20260825_001329.json"
REV = "cc35911"
SHELL = ("bash", "sh", "pwsh", "powershell", "cmd", "shell")


def load_commit(rel):
    return json.loads(subprocess.check_output(["git", "show", f"{REV}:{rel}"]).decode("utf-8"))


tmpl = {}
for fn in ["retrieval_base.json", "retrieval_middle.json", "retrieval_hard.json"]:
    d = load_commit("agent_eval/agent_eval/datasets/data/retrieval/" + fn)
    for t in d["templates"]:
        tmpl[t["id"]] = t
instr_of = {tid: t["instruction"] for tid, t in tmpl.items()}


class Inst:
    def __init__(self, t):
        self.id = t["id"]
        self.instruction = t.get("instruction", "")
        self.setup = t.get("setup", {})
        self.env = {"backend": "disk"}
        self.gold_docs = t.get("gold_docs", [])
        self.verifier = t.get("verifier", {})
        self.must_not_do = t.get("must_not_do", [])
        self.available_tools = t.get("available_tools", [])


def build_traj(tr):
    return Trajectory(
        steps=[Step(action=s["action"], observation=s.get("observation", ""),
                     state_before=s.get("state_before", {}), state_after=s.get("state_after", {}))
                for s in tr["steps"]],
        answer=tr.get("answer"),
    )


def replay_final_state(inst, traj):
    """重建磁盘 final_state = {relpath: content}，回放所有写/改/删/bash 变异。"""
    s = dict(inst.setup)
    for st in traj.steps:
        a = st.action
        tool = _tool_of(a)
        try:
            spec = json.loads(a.split(":", 1)[1]) if ":" in a else {}
        except Exception:
            spec = {}
        if tool == "write":
            s[spec.get("path")] = spec.get("content", "")
        elif tool == "edit":
            p = spec.get("path")
            if p in s:
                s[p] = s[p].replace(spec.get("old", ""), spec.get("new", ""), 1)
        elif tool == "delete":
            s.pop(spec.get("path"), None)
        elif tool == "bash":
            cmd = spec.get("command", "") if isinstance(spec, dict) else ""
            for m in re.finditer(r"cp\s+([^\s]+)\s+([^\s]+)", cmd):
                src, dst = m.group(1), m.group(2)
                if src in s:
                    if dst.endswith("/") or dst == "":
                        s[dst + src.rsplit("/", 1)[-1]] = s[src]
                    else:
                        s[dst] = s[src]
            for m in re.finditer(r"rm\s+(?:-[rf]+\s+)?([^\s]+)", cmd):
                tgt = m.group(1).rstrip("/")
                for k in list(s.keys()):
                    if k == tgt or k.startswith(tgt + "/"):
                        s.pop(k, None)
    return s


def classify(traj, inst):
    gold_norm = {_norm_path(g) for g in inst.gold_docs}
    viewed = set()
    for st in traj.steps:
        tool = _tool_of(st.action)
        if tool in READ_TOOLS:
            p = _read_path(st.action)
            if p:
                viewed.add(_norm_path(p))
        elif tool in SHELL:
            for fp in _bash_read_paths(st.action):
                viewed.add(_norm_path(fp))
    read_actions = sum(
        1 for st in traj.steps
        if _tool_of(st.action) in READ_TOOLS
        or (_tool_of(st.action) in SHELL and _bash_read_paths(st.action))
    )
    value = 0.0 if not gold_norm else round(len(gold_norm & viewed) / len(gold_norm), 4)
    missed = sorted(gold_norm - viewed)
    if read_actions == 0:
        kind = "NO_EXPLORE"
    elif value == 0.0:
        kind = "FULL_MISS"
    elif value < 1.0:
        kind = "PARTIAL"
    else:
        kind = "COVERED"
    return value, missed, read_actions, kind


def main():
    d = json.load(open(RESULT, encoding="utf-8"))
    tot, corr_pass = 0, 0
    rows = []
    for tid, t in d["templates"].items():
        seeds = []
        for i, tr in enumerate(t["trajectories"]):
            traj = build_traj(tr)
            inst = Inst(tmpl[tid])
            fs = replay_final_state(inst, traj)
            vr = verify(inst, fs, traj)          # 修复后 verifier + 真实 final_state
            value, missed, read_actions, kind = classify(traj, inst)
            tot += 1
            if vr.passed:
                corr_pass += 1
            seeds.append({
                "seed": i, "passed": vr.passed, "coverage": value,
                "missed": missed, "kind": kind, "read_actions": read_actions,
                "answer": (tr.get("answer") or "")[:90], "n_steps": len(tr["steps"]),
            })
        rows.append({
            "tid": tid, "tier": t.get("tier"), "k": len(seeds),
            "recorded_pass_k": t.get("pass_k"),
            "corrected_pass_k": round(sum(s["passed"] for s in seeds) / len(seeds), 4),
            "seeds": seeds,
        })

    print("=" * 80)
    print("PI 检索评估 — 修复度量 + 真实 final_state 重验（数据集 cc35911 改名前）")
    print("=" * 80)
    rec_overall = sum((r["recorded_pass_k"] or 0) * r["k"] for r in rows) / tot
    print(f"校正 pass_k = {corr_pass/tot:.4f}   (原产物记录旧度量 pass_k = {rec_overall:.4f})")
    print()
    print("-- 度量修复后【翻正】的模板（旧 fail → 新 pass_k）--")
    flips = [r for r in rows if (r["recorded_pass_k"] or 1) < 1.0 and r["corrected_pass_k"] > r["recorded_pass_k"]]
    for r in sorted(flips, key=lambda x: x["corrected_pass_k"] - (x["recorded_pass_k"] or 0), reverse=True):
        print(f"  {r['tid']:22s} {r['tier']:6s} 旧{r['recorded_pass_k']:.2f} → 新{r['corrected_pass_k']:.2f}")
    print()
    fails = [r for r in rows if r["corrected_pass_k"] < 1.0]
    print(f"-- 修复后【仍失败】模板: {len(fails)} 个 --")
    for r in fails:
        print(f"\n### {r['tid']}  tier={r['tier']}  校正pass_k={r['corrected_pass_k']:.2f}  旧={r['recorded_pass_k']}")
        print(f"    指令: {instr_of[r['tid']][:96]}")
        for s in r["seeds"]:
            if s["passed"]:
                continue
            print(f"    seed{s['seed']} [{s['kind']}] cov={s['coverage']} read={s['read_actions']} steps={s['n_steps']}")
            if s["missed"]:
                print(f"       漏读 gold: {s['missed']}")
            if s["answer"]:
                print(f"       答案: {s['answer']!r}")


if __name__ == "__main__":
    main()
