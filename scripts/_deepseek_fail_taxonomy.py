import json

f = "results/eval_deepseek_retrieval_keycases_20260825_203404.json"
d = json.load(open(f, encoding="utf-8"))

READ_TOOLS = {"read", "open", "cat", "view", "show"}
DISCOVERY = {"glob", "ls", "find", "search", "tree", "fd", "rg", "grep"}
BASH_READ = {"cat", "tail", "head", "less", "more", "nl", "type", "bat",
             "get-content", "gc", "sls", "select-string"}


def classify(action):
    if ":" not in action:
        return "other"
    tool, arg = action.split(":", 1)
    tool = tool.strip().lower()
    if tool in READ_TOOLS:
        return "read"
    if tool in DISCOVERY:
        return "discover"
    if tool in ("bash", "sh", "pwsh", "powershell", "cmd", "shell"):
        low = arg.lower()
        return "read" if any(b in low for b in BASH_READ) else "other"
    return "other"


def counts(tr):
    steps = tr.get("steps", [])
    r = sum(1 for s in steps if classify(s["action"]) == "read")
    disc = sum(1 for s in steps if classify(s["action"]) == "discover")
    return len(steps), r, disc


total_seeds = 0
fail_seeds = 0
zero_read_fail_seeds = 0
read_but_fail_seeds = 0

print("template                 tier    pass_k  seed0(r/d)        seed1(r/d)        type")
rows = []
for tid, t in d["templates"].items():
    total_seeds += 2
    pk = t["pass_k"]
    trajs = t["trajectories"]
    comps = [counts(tr) for tr in trajs]
    # infer failing seeds: for pass_k<1, the weaker-read seed(s) are failures.
    # pass_k=0 -> both fail; pass_k=0.5 -> one fails (assume the 0-read or fewer-read one)
    zero_read_seeds = [i for i, (n, r, dsc) in enumerate(comps) if r == 0]
    if pk == 0.0:
        failing = [0, 1]
    elif pk == 0.5:
        # one fails: pick the seed with fewer reads (0-read if any)
        if len(zero_read_seeds) >= 1:
            failing = [zero_read_seeds[0]]
        else:
            failing = [0] if comps[0][1] <= comps[1][1] else [1]
    else:
        failing = []
    for fs in failing:
        fail_seeds += 1
        if comps[fs][1] == 0:
            zero_read_fail_seeds += 1
        else:
            read_but_fail_seeds += 1
    c0 = comps[0]
    c1 = comps[1] if len(comps) > 1 else (0, 0, 0)
    typ = "NO-READ" if pk == 0.0 and all(c[1] == 0 for c in comps) else ("mixed" if pk < 1.0 else "OK")
    rows.append((tid, t["tier"], pk, c0, c1, typ))

for tid, tier, pk, c0, c1, typ in rows:
    if pk < 1.0:
        print(f"{tid:24} {tier:7} {pk:5}  s0({c0[1]}/{c0[2]})     s1({c1[1]}/{c1[2]})     {typ}")

print(f"\nTOTAL seeds={total_seeds}")
print(f"FAILING seeds (inferred) = {fail_seeds}")
print(f"  -> zero-read (glob-and-answer) = {zero_read_fail_seeds}  ({100*zero_read_fail_seeds/fail_seeds:.0f}%)")
print(f"  -> read-but-wrong/insufficient = {read_but_fail_seeds}  ({100*read_but_fail_seeds/fail_seeds:.0f}%)")
