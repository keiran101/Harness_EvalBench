import json, glob, os

# map result template id -> data file
base = "agent_eval/agent_eval/datasets/data"

# collect all tasks by id
id2task = {}
for grp, fn in [("retrieval_base","retrieval/retrieval_base.json"),
                ("retrieval_middle","retrieval/retrieval_middle.json"),
                ("retrieval_hard","retrieval/retrieval_hard.json"),
                ("retrieval_keycases","keycases/retrieval_keycases.json")]:
    path = os.path.join(base, fn)
    d = json.load(open(path, encoding="utf-8"))
    for t in d["templates"]:
        tid = t.get("id") or t.get("template_id")
        id2task[tid] = t

# load result
res = json.load(open("results/eval_deepseek_retrieval_keycases_20260825_203404.json", encoding="utf-8"))
print("recovered tasks:", len(id2task))
missing = [tid for tid in res["templates"] if tid not in id2task]
print("missing in data:", missing)

# show a sample task structure
sample_tid = "base_retrieval_007"
if sample_tid in id2task:
    t = id2task[sample_tid]
    print("\nSAMPLE task keys:", list(t.keys()))
    for k in t:
        v = t[k]
        if isinstance(v, (str,int,float,list)) and not isinstance(v,(list,)) or isinstance(v,str):
            print(f"  {k} = {repr(v)[:200]}")
        elif isinstance(v, list):
            print(f"  {k} = list[{len(v)}] {repr(v)[:200]}")

# For each FAIL/MIX template, print instruction + gold (if any)
print("\n================ FAIL/MIX task instructions ================")
for tid, t in res["templates"].items():
    if t["pass_k"] >= 1.0:
        continue
    task = id2task.get(tid, {})
    instr = task.get("instruction") or task.get("task") or task.get("prompt") or "(n/a)"
    gold = task.get("gold_docs") or task.get("gold") or task.get("answer_files")
    print(f"\n[{tid}] pk={t['pass_k']} tier={t['tier']}")
    print(f"  INSTR: {repr(instr)[:300]}")
    if gold is not None:
        print(f"  GOLD : {repr(gold)[:200]}")
    # also show fields present
    print(f"  task fields: {[k for k in task.keys()]}")
