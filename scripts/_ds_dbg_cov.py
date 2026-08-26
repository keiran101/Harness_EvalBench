import json, os, re

base = "agent_eval/agent_eval/datasets/data"
id2task = {}
for grp, fn in [("retrieval_base","retrieval/retrieval_base.json"),
                ("retrieval_middle","retrieval/retrieval_middle.json"),
                ("retrieval_hard","retrieval/retrieval_hard.json"),
                ("retrieval_keycases","keycases/retrieval_keycases.json")]:
    d = json.load(open(os.path.join(base, fn), encoding="utf-8"))
    for t in d["templates"]:
        id2task[t["id"]] = t

def extract_path(action):
    m = re.search(r'"file_path"\s*:\s*"([^"]+)"', action)
    if not m: m = re.search(r'"path"\s*:\s*"([^"]+)"', action)
    if not m:
        mm = re.search(r'(?:Get-Content|gc|cat|type|head|tail)\s+["\']?([^\s"\'|;]+)', action)
        if mm: return mm.group(1)
    return m.group(1) if m else None

def norm(p):
    p = p.strip().strip('"').strip("'").strip("`")
    p = p.replace("\\", "/")
    if p.startswith("./"): p = p[2:]
    return p

res = json.load(open("results/eval_deepseek_retrieval_keycases_20260825_203404.json", encoding="utf-8"))
for tid in ["hard_retrieval_004","hard_retrieval_006","middle_retrieval_006"]:
    t = res["templates"][tid]
    gold = [norm(g) for g in id2task[tid].get("gold_docs", [])]
    print(f"\n===== {tid}  gold_norm={gold} =====")
    for i, tr in enumerate(t["trajectories"]):
        reads = []
        for s in tr["steps"]:
            if s["action"].startswith("read:"):
                p = extract_path(s["action"])
                reads.append(norm(p) if p else f"<NONE from {s['action'][:60]}>")
        cov = (len(set(reads) & set(gold)) / len(gold)) if gold else 1.0
        print(f"  seed{i}: reads_norm={reads} -> cov={cov:.2f}")
