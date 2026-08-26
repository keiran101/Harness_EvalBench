import json, os, re, statistics as st
from collections import defaultdict, Counter

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
DISTR_WORDS = ["干扰","噪声","无关","noise","distractor","草稿","忽略","不要读","无需读","不在范围","多余","draft","ignore","irrelevant"]

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
    m = re.search(r'"file_path"\s*:\s*"([^"]+)"', action)
    if not m: m = re.search(r'"path"\s*:\s*"([^"]+)"', action)
    if not m:
        mm = re.search(r'(?:Get-Content|gc|cat|type|head|tail)\s+["\']?([^\s"\'|;]+)', action)
        if mm: return mm.group(1)
    return m.group(1) if m else None

def norm(p):
    p = p.strip().strip('"').strip("'").strip("`")
    p = p.replace("\\", "/")
    p = re.sub(r"/+", "/", p)
    if p.startswith("./"): p = p[2:]
    return p

res = json.load(open("results/eval_deepseek_retrieval_keycases_20260825_203404.json", encoding="utf-8"))

rows = []
for tid, t in res["templates"].items():
    task = id2task[tid]
    gold = [norm(g) for g in task.get("gold_docs", [])]
    instr = task.get("instruction", "")
    instr_distr = any(w in instr for w in DISTR_WORDS)
    pk = t["pass_k"]
    for tr in t["trajectories"]:
        steps = tr["steps"]
        reads, disc, other = [], [], []
        tools = set()
        for s in steps:
            c, tool = classify(s["action"])
            tools.add(tool)
            if c == "read":
                reads.append(tool)
                p = extract_path(s["action"])
                if p: other.append(("READPATH", norm(p)))
            elif c == "discover":
                disc.append(tool)
            else:
                other.append((tool, s["action"][:40]))
        read_paths = [norm(p) for _, p in other if _ == "READPATH"]
        rc = len(read_paths)
        dc = len(disc)
        cov = (len(set(read_paths) & set(gold)) / len(gold)) if gold else 1.0
        # env features from first step state_before
        sb = steps[0].get("state_before", {}) if steps else {}
        env_files = list(sb.keys()) if isinstance(sb, dict) else []
        env_n = len(env_files)
        distr_in_env = sum(1 for v in sb.values() if isinstance(v, str) and any(w in v for w in DISTR_WORDS)) if isinstance(sb, dict) else 0
        # label assignment respecting pass_k
        if pk == 1.0: label = 1
        elif pk == 0.0: label = 0
        else: label = 1 if cov >= 1.0 else 0
        rows.append(dict(
            tid=tid, tier=t["tier"], capability=task.get("capability",""),
            pk=pk, label=label, cov=cov, gold_n=len(gold),
            env_n=env_n, distr_env=distr_in_env, instr_distr=instr_distr,
            read_count=rc, disc_count=dc, n_tools=len(tools),
            used_read=(rc>0), glob_only=(dc>0 and rc==0),
            latency=tr.get("latency_ms",0), req=tr.get("request_count",0),
        ))

PASS = [r for r in rows if r["label"]==1]
FAIL = [r for r in rows if r["label"]==0]
print(f"TOTAL traj={len(rows)}  PASS={len(PASS)}  FAIL={len(FAIL)}  (pass_k-derived)")

def mean(xs): return sum(xs)/len(xs) if xs else float('nan')

print("\n===== A. TOOL USAGE vs PASS/FAIL =====")
print(f"{'metric':22} | {'PASS':>8} | {'FAIL':>8}")
print(f"{'used_read (rate)':22} | {mean([r['used_read'] for r in PASS]):8.3f} | {mean([r['used_read'] for r in FAIL]):8.3f}")
print(f"{'glob_only (rate)':22} | {mean([r['glob_only'] for r in PASS]):8.3f} | {mean([r['glob_only'] for r in FAIL]):8.3f}")
print(f"{'mean read_count':22} | {mean([r['read_count'] for r in PASS]):8.2f} | {mean([r['read_count'] for r in FAIL]):8.2f}")
print(f"{'mean disc_count':22} | {mean([r['disc_count'] for r in FAIL if False] or [r['disc_count'] for r in PASS]):8.2f} | {mean([r['disc_count'] for r in FAIL]):8.2f}")
print(f"{'mean n_tools':22} | {mean([r['n_tools'] for r in PASS]):8.2f} | {mean([r['n_tools'] for r in FAIL]):8.2f}")
# 0-read -> fail precision
zero_read = [r for r in rows if not r['used_read']]
print(f"\n0-read trajectories: {len(zero_read)}  of which FAIL={sum(r['label']==0 for r in zero_read)}  (0-read->FAIL rate={sum(r['label']==0 for r in zero_read)/len(zero_read):.3f})")
used_read_pass = [r for r in rows if r['used_read']]
print(f"used-read trajectories: {len(used_read_pass)}  of which PASS={sum(r['label']==1 for r in used_read_pass)}  (read->PASS rate={sum(r['label']==1 for r in used_read_pass)/len(used_read_pass):.3f})")

print("\n===== B. DATASET FEATURES vs PASS/FAIL =====")
print(f"{'metric':22} | {'PASS':>8} | {'FAIL':>8}")
print(f"{'gold_n (mean)':22} | {mean([r['gold_n'] for r in PASS]):8.2f} | {mean([r['gold_n'] for r in FAIL]):8.2f}")
print(f"{'env_n (mean)':22} | {mean([r['env_n'] for r in PASS]):8.2f} | {mean([r['env_n'] for r in FAIL]):8.2f}")
print(f"{'distr_env (mean)':22} | {mean([r['distr_env'] for r in PASS]):8.2f} | {mean([r['distr_env'] for r in FAIL]):8.2f}")
# fail-rate by distractor flag (env)
def fail_rate(sub): 
    if not sub: return float('nan')
    return sum(r['label']==0 for r in sub)/len(sub)
fr_instr_y = fail_rate([r for r in rows if r['instr_distr']])
fr_instr_n = fail_rate([r for r in rows if not r['instr_distr']])
print(f"\nfail-rate | instr_has_distractor={fr_instr_y:.3f}  vs  no_distractor={fr_instr_n:.3f}")
fr_env_y = fail_rate([r for r in rows if r['distr_env']>0])
fr_env_n = fail_rate([r for r in rows if r['distr_env']==0])
print(f"fail-rate | env_has_distractor={fr_env_y:.3f}  vs  no_distractor={fr_env_n:.3f}")

print("\n===== C. JOINT: fail-rate & read-skip by gold_n bucket =====")
buckets = [(1,2,"1-2"),(3,4,"3-4"),(5,99,"5+")]
for lo,hi,lab in buckets:
    sub=[r for r in rows if lo<=r['gold_n']<=hi]
    if not sub: continue
    print(f"  gold_n {lab:4}: n={len(sub):2} fail={fail_rate(sub):.3f} read_skip={mean([not r['used_read'] for r in sub]):.3f} mean_reads={mean([r['read_count'] for r in sub]):.2f}")

print("\n===== C2. JOINT: by tier (fail + read-skip + mean gold/env/distr) =====")
for tier in ["base","middle","hard"]:
    sub=[r for r in rows if r['tier']==tier]
    print(f"  {tier:7}: n={len(sub):2} fail={fail_rate(sub):.3f} read_skip={mean([not r['used_read'] for r in sub]):.3f} gold_n={mean([r['gold_n'] for r in sub]):.2f} env_n={mean([r['env_n'] for r in sub]):.2f} distr_env={mean([r['distr_env'] for r in sub]):.2f}")

print("\n===== C3. JOINT: env distractor count vs read-skip & fail =====")
for dc_lab, pred in [("0",lambda r:r['distr_env']==0),("1-2",lambda r:1<=r['distr_env']<=2),("3+",lambda r:r['distr_env']>=3)]:
    sub=[r for r in rows if pred(r)]
    if not sub: continue
    print(f"  env_distr {dc_lab:3}: n={len(sub):2} fail={fail_rate(sub):.3f} read_skip={mean([not r['used_read'] for r in sub]):.3f} mean_cov={mean([r['cov'] for r in sub]):.3f}")

# save rows
json.dump(rows, open("scripts/_ds_joint_rows.json","w"), ensure_ascii=False, indent=1)
print("\nsaved scripts/_ds_joint_rows.json")
