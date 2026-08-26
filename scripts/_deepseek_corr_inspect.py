import json
f = "results/eval_deepseek_retrieval_keycases_20260825_203404.json"
d = json.load(open(f, encoding="utf-8"))

# template-level keys
tid0 = list(d["templates"].keys())[0]
t0 = d["templates"][tid0]
print("TEMPLATE keys:", list(t0.keys()))
for k in t0:
    v = t0[k]
    if isinstance(v, (str, int, float, bool, type(None))):
        print(f"  {k} = {repr(v)[:120]}")
    elif isinstance(v, list):
        print(f"  {k} = list[{len(v)}] sample={repr(v)[:160]}")
    elif isinstance(v, dict):
        print(f"  {k} = dict keys={list(v.keys())[:20]}")

# trajectory-level keys
print("\n--- trajectory[0] keys ---")
tr = t0["trajectories"][0]
print("traj keys:", list(tr.keys()))
for k in tr:
    v = tr[k]
    if isinstance(v, (str, int, float, bool, type(None))):
        print(f"  {k} = {repr(v)[:160]}")
    elif isinstance(v, list):
        print(f"  {k} = list[{len(v)}]")
    elif isinstance(v, dict):
        print(f"  {k} = dict keys={list(v.keys())[:20]}")

# one step
print("\n--- step[0] keys ---")
if tr.get("steps"):
    s = tr["steps"][0]
    print("step keys:", list(s.keys()))
    print(json.dumps(s, ensure_ascii=False)[:400])

# how many templates have gold_docs / instruction / reference
has_gold = sum(1 for t in d["templates"].values() if t.get("gold_docs") is not None)
has_instr = sum(1 for t in d["templates"].values() if t.get("instruction") is not None)
print("\ntemplates with gold_docs:", has_gold, "/", len(d["templates"]))
print("templates with instruction:", has_instr)

# sample gold_docs and instruction from one
for tid, t in d["templates"].items():
    if t.get("gold_docs") is not None:
        print(f"\nSample gold_docs [{tid}]:", repr(t["gold_docs"])[:300])
        print(f"Sample instruction [{tid}]:", repr(t.get("instruction"))[:300])
        break
