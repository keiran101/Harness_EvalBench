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

READ_TOOLS = {"read","open","cat","view","show"}
DISCOVERY = {"glob","ls","find","search","tree","fd","rg"}
BASH_READ = {"cat","tail","head","less","more","nl","type","bat","Get-Content","gc","sls","Select-String"}

def classify(action):
    if ":" not in action: return ("other", action)
    tool, arg = action.split(":", 1)
    tool = tool.strip()
    if tool in READ_TOOLS: return ("read", tool)
    if tool in DISCOVERY: return ("discover", tool)
    if tool in ("bash","sh","pwsh","powershell","cmd","shell","shell-exec"):
        low = arg.lower()
        if any(b.lower() in low for b in BASH_READ): return ("read", tool)
        return ("other", tool)
    return ("other", tool)

res = json.load(open("results/eval_deepseek_retrieval_keycases_20260825_203404.json", encoding="utf-8"))

for tid in ["hard_retrieval_004","hard_retrieval_006","middle_retrieval_006"]:
    t = res["templates"][tid]
    gold = id2task[tid].get("gold_docs", [])
    print(f"\n===== {tid}  pass_k={t['pass_k']}  gold={gold} =====")
    for i, tr in enumerate(t["trajectories"]):
        print(f"-- seed{i}: {len(tr['steps'])} steps --")
        for s in tr["steps"]:
            c, _ = classify(s["action"])
            if c in ("read","discover"):
                print(f"   [{c}] {s['action'][:140]}")
