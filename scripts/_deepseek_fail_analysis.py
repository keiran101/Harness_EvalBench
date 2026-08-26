import json

f = "results/eval_deepseek_retrieval_keycases_20260825_203404.json"
d = json.load(open(f, encoding="utf-8"))

READ_TOOLS = {"read", "open", "cat", "view", "show"}
DISCOVERY = {"glob", "ls", "find", "search", "tree", "fd", "rg", "grep"}
BASH_READ = {"cat", "tail", "head", "less", "more", "nl", "type", "bat",
             "get-content", "gc", "sls", "select-string"}


def classify(action):
    if ":" not in action:
        return ("other", action)
    tool, arg = action.split(":", 1)
    tool = tool.strip().lower()
    if tool in READ_TOOLS:
        return ("read", tool)
    if tool in DISCOVERY:
        return ("discover", tool)
    if tool in ("bash", "sh", "pwsh", "powershell", "cmd", "shell"):
        low = arg.lower()
        if any(b in low for b in BASH_READ):
            return ("read", tool)
        return ("other", tool)
    return ("other", tool)


def analyze_traj(tr):
    steps = tr.get("steps", [])
    n = len(steps)
    reads = [s for s in steps if classify(s["action"])[0] == "read"]
    disc = [s for s in steps if classify(s["action"])[0] == "discover"]
    errs = [s for s in steps if s.get("is_error")]
    return n, len(reads), len(disc), len(errs), [s.get("error_category") for s in errs]


print("=== DEEPSEEK failing-template per-seed attribution (TRUE read class) ===\n")
fails = [tid for tid, t in d["templates"].items() if t["pass_k"] < 1.0]
for tid in fails:
    t = d["templates"][tid]
    print(f"### {tid}  tier={t['tier']}  pass_k={t['pass_k']}  "
          f"seed_stab={t['robustness']['detail']['seed_stability']} "
          f"sens={t['robustness']['detail']['seed_sensitivity']}")
    for i, tr in enumerate(t["trajectories"]):
        n, r, disc, e, ecats = analyze_traj(tr)
        passed = tr.get("passed", "n/a")
        print(f"   seed{i}: passed={passed} steps={n} TRUE_reads={r} "
              f"discover={disc} errors={e} errcats={ecats}")
    print()
