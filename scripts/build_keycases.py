import json, os, copy

RETR = "agent_eval/agent_eval/datasets/data/retrieval"
KEYC = "agent_eval/agent_eval/datasets/data/keycases"

hard = json.load(open(f"{RETR}/retrieval_hard.json", encoding="utf-8"))
mid = json.load(open(f"{RETR}/retrieval_middle.json", encoding="utf-8"))


def get(group, tid):
    for t in group["templates"]:
        if t["id"] == tid:
            return t
    raise KeyError(tid)


# ---------- 1) keycases = 原始版（deepcopy，避免与原集对象共享引用） ----------
h2_orig = get(hard, "hard_retrieval_002")
m4_orig = get(mid, "middle_retrieval_004")
keycases = {
    "group": "retrieval_keycases",
    "templates": [copy.deepcopy(h2_orig), copy.deepcopy(m4_orig)],  # 独立副本，后续改原集不影响它
    "field_annotations": {
        "hard_retrieval_002": {
            "instruction": "诊断要点：原始模糊指令『提取并汇报』可被『只 ls/find 列文件名』绕过——答案即文件名本身。"
                           "本集保留此易错点，观测 agent 是否真 read 内容还是仅列名。",
            "gold_docs": "retrieval_covered 核心：须 read/open/cat 覆盖 pay_api.md/pay_callback.md/pay_refund.md，覆盖率==1.0 才过",
            "verifier.fail_to_pass[retrieval_covered]": "轨迹是否用读工具覆盖全部目标文件（不含 ls/find/bash cat）",
            "verifier.pass_to_pass[file_content_eq]": "回归保护：噪声 risk_model.md 未被篡改",
            "verifier.pass_to_pass[file_not_exists]": "副作用检查：未产生额外文件(如 pay/_tmp.md)",
            "reference_answer": "若只列文件名则 human 判『对』但 verifier 判挂——本集正是要暴露这种不一致",
            "available_tools": "read/ls/find 分工：read 取内容，ls/find 仅定位"
        },
        "middle_retrieval_004": {
            "instruction": "诊断要点：原始指令要『汇报版本号』，而版本号就在文件名(001/002/003)里，"
                           "agent 可只 ls 即得答案、不读内容。保留此易错点观测不 read 行为。",
            "gold_docs": "retrieval_covered 覆盖目标：3 个正式 .sql",
            "verifier.fail_to_pass[retrieval_covered]": "轨迹须用 read 覆盖 3 个正式迁移脚本",
            "verifier.pass_to_pass[file_content_eq]": "tmp/scratch.sql 内容未被改动",
            "reference_answer": "版本号可由文件名推——本集刻意保留，看 agent 是否读内容",
            "available_tools": "read/ls/find 分工"
        }
    }
}

# ---------- 2) 原集只改 hard_002 / middle_004 指令（堵不 read 漏洞，改指令不改文件名） ----------
for t in hard["templates"]:
    if t["id"] == "hard_retrieval_002":
        t["instruction"] = (
            "仓库含支付（pay）与风控（risk）两大模块文档混放。"
            "请先定位支付模块核心三份（pay_api.md、pay_callback.md、pay_refund.md），"
            "再用 read 工具实际读取每份的完整内容，并汇报各自的关键要点"
            "（例如 pay_api 定义了哪些接口、pay_callback 处理什么）；"
            "risk/ 与 pay_draft/ 是噪声，不要读取。仅列出文件名或路径视为未完成。"
        )

for t in mid["templates"]:
    if t["id"] == "middle_retrieval_004":
        t["instruction"] = (
            "找出 migrations/ 下所有正式迁移脚本（.sql 文件），用 read 工具实际读取每个脚本的内容，"
            "并汇报每份脚本『具体做了什么』（建表 / 加字段 / 加索引等）；"
            "migrations/tmp/ 下是草稿，不要读取。仅根据文件名推断版本号视为未完成。"
        )


def dump(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n")


dump(f"{KEYC}/retrieval_keycases.json", keycases)
dump(f"{RETR}/retrieval_hard.json", hard)
dump(f"{RETR}/retrieval_middle.json", mid)
print("done: keycases ->", KEYC, "| hard/middle fixed in place")
