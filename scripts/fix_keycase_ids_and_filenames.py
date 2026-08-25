#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""修复 keycases 的 id 冲突，并原集堵漏靠改文件名（不改指令语义）。

1) keycases: 把 hard_retrieval_002 / middle_retrieval_004 改为
   keycases_hard_002 / keycases_middle_004（保留原始指令/setup/gold_docs）。
2) 原集 hard_002: 改名 pay_api/callback/refund.md -> s1/s2/s3.md，
   指令删去括号内文件名列表（其余不动）——这是"改文件名"下唯一自洽写法。
3) 原集 middle_004: 改名 001_init/002_add_idx/003_arch.sql ->
   init/add_idx/arch.sql（版本号移出文件名），指令一字不改。
"""
import json
import os
import copy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY = os.path.join(ROOT, "agent_eval/agent_eval/datasets/data/keycases/retrieval_keycases.json")
HARD = os.path.join(ROOT, "agent_eval/agent_eval/datasets/data/retrieval/retrieval_hard.json")
MID = os.path.join(ROOT, "agent_eval/agent_eval/datasets/data/retrieval/retrieval_middle.json")


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save(p, d):
    with open(p, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)
        f.write("\n")


# ---------- 1) keycases：改 id，保留原始内容 ----------
kc = load(KEY)
rename_map = {"hard_retrieval_002": "keycases_hard_002",
              "middle_retrieval_004": "keycases_middle_004"}
new_templates = []
for t in kc["templates"]:
    tid = t["id"]
    if tid in rename_map:
        t = copy.deepcopy(t)
        t["id"] = rename_map[tid]
    new_templates.append(t)
kc["templates"] = new_templates

new_fa = {}
for old_key, ann in kc.get("field_annotations", {}).items():
    new_fa[rename_map.get(old_key, old_key)] = ann
kc["field_annotations"] = new_fa
save(KEY, kc)
print("[keycases] ids ->", [t["id"] for t in kc["templates"]])


# ---------- 2) 原集 hard_002：改名 + 指令去文件名列表 ----------
hard = load(HARD)
fmap = {"pay_api.md": "s1.md", "pay_callback.md": "s2.md", "pay_refund.md": "s3.md"}
for t in hard["templates"]:
    if t["id"] != "hard_retrieval_002":
        continue
    new_setup = {fmap.get(p, p): c for p, c in t["setup"].items()}
    t["setup"] = new_setup
    t["gold_docs"] = [fmap.get(g, g) for g in t["gold_docs"]]
    for step in t.get("reference_plan", []):
        if step.get("tool") == "read":
            p = step["args"]["path"]
            step["args"]["path"] = fmap.get(p, p)
    t["instruction"] = ("仓库含支付（pay）与风控（risk）两大模块文档混放。"
                        "请只提取支付模块的核心三份并汇报各自关键要点；"
                        "risk/ 与 pay_draft/ 是噪声")
    for chk in t["verifier"].get("pass_to_pass", []):
        if chk["fn"] == "file_not_exists":
            chk["args"]["path"] = "s_tmp.md"
    t["expected_outcome"] = ("精准读取 3 份支付核心文档（s1/s2/s3），覆盖率=1；"
                             "risk/、pay_draft/ 为噪声")
save(HARD, hard)
h2 = [t for t in hard["templates"] if t["id"] == "hard_retrieval_002"][0]
print("[hard_002] setup keys ->", list(h2["setup"].keys()))
print("[hard_002] gold_docs ->", h2["gold_docs"])
print("[hard_002] instruction ->", h2["instruction"][:55], "...")


# ---------- 3) 原集 middle_004：改名（去版本号），指令不动 ----------
mid = load(MID)
# 文件名映射（仅文件名部分），保留 "migrations/" 前缀
fmap4 = {"001_init.sql": "init.sql", "002_add_idx.sql": "add_idx.sql", "003_arch.sql": "arch.sql"}


def remap_path(p):
    if "/" in p:
        d, fn = p.rsplit("/", 1)
        return d + "/" + fmap4.get(fn, fn)
    return fmap4.get(p, p)


for t in mid["templates"]:
    if t["id"] != "middle_retrieval_004":
        continue
    t["setup"] = {remap_path(p): c for p, c in t["setup"].items()}
    t["gold_docs"] = [remap_path(g) for g in t["gold_docs"]]
    for step in t.get("reference_plan", []):
        if step.get("tool") == "read":
            step["args"]["path"] = remap_path(step["args"]["path"])
save(MID, mid)
m4 = [t for t in mid["templates"] if t["id"] == "middle_retrieval_004"][0]
print("[middle_004] instruction unchanged ->", m4["instruction"][:40], "...")
print("[middle_004] setup keys ->", list(m4["setup"].keys()))
print("[middle_004] gold_docs ->", m4["gold_docs"])
print("DONE")
