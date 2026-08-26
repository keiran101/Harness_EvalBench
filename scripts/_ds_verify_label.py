import json, os, re
from collections import defaultdict

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

def extract_path(action):
    if ":" not in action: return None
    tool, arg = action.split(":", 1)
    tool = tool.strip()
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

n_templates = len(res["templates"])
n_traj = 0
mismatch = 0
for tid, t in res["templates"].items():
    gold = [norm(g) for g in id2task[tid].get("gold_docs", [])]
    labels = []
    for tr in t["trajectories"]:
        reads = []
        for s in tr["steps"]:
            c, _ = classify(s["action"])
            if c == "read":
                p = extract_path(s["action"])
                if p: reads.append(norm(p))
        cov = (len(set(reads) & set(gold)) / len(gold)) if gold else 1.0
        label = 1.0 if cov >= 1.0 else 0.0
        labels.append(label)
        n_traj += 1
    # verify mean(label) == pass_k
    if abs(sum(labels)/len(labels) - t["pass_k"]) > 0.01:
        mismatch += 1
        print(f"  MISMATCH {tid}: pass_k={t['pass_k']} labels={labels}")

print(f"templates={n_templates} trajectories={n_traj}")
print(f"label-vs-pass_k mismatches = {mismatch} (0 means coverage-derived label is fully consistent)")
