import json
res = json.load(open("results/eval_deepseek_retrieval_keycases_20260825_203404.json", encoding="utf-8"))
# find a PASS template (pk==1.0)
for tid,t in res["templates"].items():
    if t["pass_k"]==1.0:
        print("PASS template:", tid)
        for i,tr in enumerate(t["trajectories"]):
            print(f"  -- traj {i} steps={len(tr['steps'])}")
            for s in tr["steps"]:
                print("     ACTION:", repr(s["action"])[:160])
        break
# also a FAIL template to see format
for tid,t in res["templates"].items():
    if t["pass_k"]==0.0:
        print("\nFAIL template:", tid)
        for i,tr in enumerate(t["trajectories"]):
            print(f"  -- traj {i} steps={len(tr['steps'])}")
            for s in tr["steps"]:
                print("     ACTION:", repr(s["action"])[:160])
        break
