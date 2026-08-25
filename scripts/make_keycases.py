import json, os

DATA = "agent_eval/agent_eval/datasets/data/retrieval"
# 统一追加的"明确指令"从句：强制要求 read 内容，不能只列文件名
CLARIFY = "（注意：须用 read 工具实际读取目标文件内容并据此汇报，仅列出文件名或定位文件不算完成）"


def load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def pop_by_id(group, tid):
    for i, t in enumerate(group["templates"]):
        if t["id"] == tid:
            return group["templates"].pop(i)
    raise KeyError(tid)


hard = load(f"{DATA}/retrieval_hard.json")
mid = load(f"{DATA}/retrieval_middle.json")
base = load(f"{DATA}/retrieval_base.json")

# 1) 从原集中抽出两个关键 case
h2 = pop_by_id(hard, "hard_retrieval_002")
m4 = pop_by_id(mid, "middle_retrieval_004")

# 2) 关键 case 的指令改明确（强制读内容、且 middle_004 改为要求汇报"做了什么"而非版本号）
h2["instruction"] = (
    "仓库含支付（pay）与风控（risk）两大模块文档混放。请先用 ls/find 定位、"
    "再用 read 工具实际读取支付模块核心三份（pay_api.md、pay_callback.md、pay_refund.md）"
    "的完整内容，并汇报每份的关键要点；risk/ 与 pay_draft/ 是噪声，不要读取。"
    "仅列出文件名或路径视为未完成。"
)
m4["instruction"] = (
    "请找出 migrations/ 下所有正式迁移脚本（.sql 文件），用 read 工具实际读取每个脚本的内容，"
    "并汇报每份脚本『具体做了什么』（而不仅是版本号）；migrations/tmp/ 下是草稿，不要读取。"
    "仅根据文件名推断视为未完成。"
)

# 3) 关键 case 单独成集，并标注每个字段考察什么
keycases = {
    "group": "retrieval_keycases",
    "templates": [h2, m4],
    "field_annotations": {
        "hard_retrieval_002": {
            "instruction": "考察：多模块混放+噪声目录下按模块名(pay)精准筛选目标子集并抗噪声；"
                           "明确 read 内容要求后，验证 agent 是否真正读取而非仅列名",
            "setup": "考察：gold 与噪声(risk_*、pay_draft/)同目录混放，gold 内容即评分依据",
            "gold_docs": "考察：retrieval_covered 核心——要求 read/open/cat 覆盖全部 gold，覆盖率==1.0 才过",
            "verifier.fail_to_pass[retrieval_covered]": "核心判据：轨迹是否用读工具覆盖全部目标文件(不含 ls/find/bash cat)",
            "verifier.pass_to_pass[file_content_eq]": "回归保护：噪声文件 risk_model.md 内容未被篡改",
            "verifier.pass_to_pass[file_not_exists]": "副作用检查：未产生额外文件(如 pay/_tmp.md)",
            "reference_answer": "考察：能否准确汇报目标文件实际内容要点(pay_api: 下单接口…)而非仅文件名",
            "available_tools": "考察：给定 read/ls/find，是否正确选用 read 取内容、ls/find 仅用于定位"
        },
        "middle_retrieval_004": {
            "instruction": "考察：从规律命名的迁移脚本中定位全部目标，并『读内容』汇报每个脚本做了什么；"
                           "修正前版本号在文件名里、答案可从文件名推——故改为要求汇报脚本实际作用",
            "setup": "考察：migrations/ 下 3 个正式脚本 + 1 个 tmp 草稿，gold 内容=实际迁移动作",
            "gold_docs": "retrieval_covered 覆盖目标：3 个正式 .sql",
            "verifier.fail_to_pass[retrieval_covered]": "轨迹须用 read 覆盖 3 个正式迁移脚本",
            "verifier.pass_to_pass[file_content_eq]": "tmp/scratch.sql 内容未被改动",
            "reference_answer": "要求『每个脚本做了什么』→ 必须读内容才能答(v1: 建表…)，文件名只给版本号不够",
            "available_tools": "read/ls/find 分工"
        }
    }
}

# 4) 原集剩余指令统一追加"须读内容"从句
def clarify(group):
    for t in group["templates"]:
        ins = t.get("instruction", "")
        if CLARIFY not in ins:
            t["instruction"] = ins.rstrip("。") + "。" + CLARIFY


clarify(hard)
clarify(mid)
clarify(base)


def dump(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n")


dump(f"{DATA}/retrieval_hard.json", hard)
dump(f"{DATA}/retrieval_middle.json", mid)
dump(f"{DATA}/retrieval_base.json", base)
dump(f"{DATA}/retrieval_keycases.json", keycases)

# 5) 校验：无重复 id、总数与 gold 一致
all_ids = []
for fn in ["retrieval_base.json", "retrieval_middle.json",
           "retrieval_hard.json", "retrieval_keycases.json"]:
    d = load(f"{DATA}/{fn}")
    all_ids += [t["id"] for t in d["templates"]]
dups = [x for x in set(all_ids) if all_ids.count(x) > 1]
print("files:", 4)
print("total templates:", len(all_ids), "unique:", len(set(all_ids)))
print("duplicates:", dups)
print("keycases group:", keycases["group"], "n=", len(keycases["templates"]))
print("annotations keys:", list(keycases["field_annotations"].keys()))
