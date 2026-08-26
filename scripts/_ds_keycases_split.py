import json, os, re
from collections import Counter

res = json.load(open("results/eval_deepseek_retrieval_keycases_20260825_203404.json", encoding="utf-8"))
rows = json.load(open("scripts/_ds_joint_rows.json", encoding="utf-8"))

def fr(sub): return sum(r['label']==0 for r in sub)/len(sub) if sub else float('nan')
def mean(xs): return sum(xs)/len(xs) if xs else float('nan')

print("===== DATASET SOURCE: keycases vs retrieval =====")
kc  = [r for r in rows if "keycases" in r["tid"]]
non = [r for r in rows if "keycases" not in r["tid"]]
for name, sub in [("keycases", kc), ("retrieval(non-kc)", non)]:
    print(f"  {name:16}: n={len(sub):2} fail={fr(sub):.3f} read_skip={mean([not r['used_read'] for r in sub]):.3f} "
          f"gold_n={mean([r['gold_n'] for r in sub]):.2f} env_n={mean([r['env_n'] for r in sub]):.2f} distr_env={mean([r['distr_env'] for r in sub]):.2f}")

# example trajectories: one plain-skip error, one distractor-triggered skip
print("\n===== EXAMPLE 1: skip-read error in a SIMPLE task (no distractor) =====")
for tid in ["base_retrieval_007","hard_retrieval_002","middle_retrieval_005"]:
    t = res["templates"].get(tid)
    if not t: continue
    for i,tr in enumerate(t["trajectories"]):
        if tr and tr["steps"] and all("read:" not in s["action"] for s in tr["steps"]):
            print(f"  {tid} seed{i} (env_n={rows and ''}):")
            for s in tr["steps"]:
                print(f"     {s['action'][:90]}")
            break

print("\n===== EXAMPLE 2: distractor task where it skipped despite being capable =====")
for tid in ["keycases_middle_004","keycases_hard_002","hard_retrieval_006"]:
    t = res["templates"].get(tid)
    if not t: continue
    for i,tr in enumerate(t["trajectories"]):
        steps=tr["steps"]
        if steps and all("read:" not in s["action"] for s in steps):
            print(f"  {tid} seed{i}:")
            for s in steps:
                print(f"     {s['action'][:90]}")
            break
