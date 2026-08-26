import json, os, re, statistics as st
from collections import Counter

base = "agent_eval/agent_eval/datasets/data"
id2task = {}
for grp, fn in [("retrieval_base","retrieval/retrieval_base.json"),
                ("retrieval_middle","retrieval/retrieval_middle.json"),
                ("retrieval_hard","retrieval/retrieval_hard.json"),
                ("retrieval_keycases","keycases/retrieval_keycases.json")]:
    d = json.load(open(os.path.join(base, fn), encoding="utf-8"))
    for t in d["templates"]:
        id2task[t["id"]] = t

res = json.load(open("results/eval_deepseek_retrieval_keycases_20260825_203404.json", encoding="utf-8"))

READ = {"read","open","cat","view","show","type","less","more","nl","bat","Get-Content","gc","sls","Select-String","head","tail"}
SHELL_FAM = {"bash","sh","shell","cmd","pwsh","powershell"}

def norm(p):
    p = p.strip().strip('"').strip("'").strip('`')
    p = p.replace("\\", "/")   # normalize Windows backslash
    if p.startswith("./"): p = p[2:]
    return p

def extract_read_paths(action):
    if ":" not in action: return []
    tool, arg = action.split(":",1)
    tool = tool.strip()
    paths = []
    if tool in READ:
        try:
            j = json.loads(arg)
            if isinstance(j, dict):
                for k in ("file_path","path","file","filename","target"):
                    if k in j and isinstance(j[k], str):
                        paths.append(norm(j[k]))
        except Exception:
            m = re.search(r'"(?:file_path|path)"\s*:\s*"([^"]+)"', arg)
            if m: paths.append(norm(m.group(1)))
    elif tool in SHELL_FAM:
        low = arg.lower()
        # Get-Content a.log, b.log | ...  -> capture the file list
        for m in re.finditer(r'get-content\s+([^\|\n;]+)', low):
            chunk = m.group(1)
            for tok in re.split(r'[,\s]+', chunk):
                tok = tok.strip('`.,)')
                if tok and ('/' in tok or '.' in tok or tok.endswith('log') or tok.endswith('md') or tok.endswith('sql') or tok.endswith('yaml') or tok.endswith('yml') or tok.endswith('txt') or tok.endswith('rule') or tok.endswith('conf')):
                    paths.append(norm(tok))
        for pat in (r'\bcat\s+([^\s|<>;]+)', r'\bhead\s+([^\s|<>;]+)', r'\btail\s+([^\s|<>;]+)',
                    r'\btype\s+([^\s|<>;]+)', r'\bgc\s+([^\s|<>;]+)'):
            for m in re.finditer(pat, low):
                paths.append(norm(m.group(1)))
    return paths

def traj_reads(tr):
    paths = []
    for s in tr.get("steps", []):
        paths += extract_read_paths(s["action"])
    return paths

rows = []
for tid, t in res["templates"].items():
    gold = set(norm(g) for g in id2task[tid].get("gold_docs", []))
    task = id2task[tid]
    instr = task.get("instruction","")
    has_distractor = any(w in instr for w in ["干扰","噪声","noise","draft","草稿","忽略","不在范围","不要读","无需读"])
    for tr in t["trajectories"]:
        rd = traj_reads(tr)
        rd_set = set(rd)
        hit = len(rd_set & gold)
        cov = hit/len(gold) if gold else (1.0 if rd_set else 0.0)
        rows.append(dict(tid=tid, tier=t["tier"], pk=t["pass_k"], gold_n=len(gold),
                         has_distractor=has_distractor, n_read=len(rd), n_unique=len(rd_set),
                         coverage=cov, hit=hit, gold=gold))

P = [r for r in rows if r["pk"]==1.0]
F = [r for r in rows if r["pk"]==0.0]
print(f"Trajectories labeled: PASS={len(P)} FAIL={len(F)}  MIX(0.5)={sum(1 for r in rows if r['pk']==0.5)}")

print(f"\n=== 1. COVERAGE (gold-grounded) ===")
print(f"PASS coverage mean={st.mean([r['coverage'] for r in P]):.3f} min={min(r['coverage'] for r in P):.2f}  reads/traj mean={st.mean([r['n_read'] for r in P]):.2f}")
print(f"FAIL coverage mean={st.mean([r['coverage'] for r in F]):.3f} min={min(r['coverage'] for r in F):.2f}  reads/traj mean={st.mean([r['n_read'] for r in F]):.2f}")
print(f"PASS hit/gold={st.mean([r['hit'] for r in P]):.2f}/{st.mean([r['gold_n'] for r in P]):.1f}")
print(f"FAIL hit/gold={st.mean([r['hit'] for r in F]):.2f}/{st.mean([r['gold_n'] for r in F]):.1f}")

print(f"\n=== 2. TAXONOMY (gold-grounded) ===")
zero=[r for r in F if r["n_read"]==0]
partial=[r for r in F if r["n_read"]>0 and r["coverage"]<1.0]
full=[r for r in F if r["coverage"]>=1.0]
print(f"  A. 0 reads (skipped): {len(zero)}/{len(F)} = {len(zero)/len(F):.0%}")
print(f"  B. read but coverage<1: {len(partial)}/{len(F)} = {len(partial)/len(F):.0%}")
print(f"  C. coverage>=1 yet failed: {len(full)}")
print(f"  -> wrong-selection FAIL details: {[(r['tid'],r['hit'],r['gold_n'],r['n_read']) for r in partial]}")

print(f"\n=== 3. READ necessary? ===")
print(f"  PASS 0-read: {sum(1 for r in P if r['n_read']==0)}/{len(P)}")
print(f"  FAIL 0-read: {sum(1 for r in F if r['n_read']==0)}/{len(F)}")
allrows=P+F
pf=sum(1 for r in allrows if r['n_read']==0 and r['pk']==0.0); tot0=sum(1 for r in allrows if r['n_read']==0)
print(f"  '0-read->FAIL' precision={pf/max(1,tot0):.0%} recall={len(zero)/len(F):.0%}")
pr=sum(1 for r in allrows if r['n_read']>0 and r['pk']==1.0); totR=sum(1 for r in allrows if r['n_read']>0)
print(f"  'read>=1->PASS' precision={pr/max(1,totR):.0%}")

print(f"\n=== 4. CORRELATES ===")
print(f"  gold_n: PASS mean={st.mean([r['gold_n'] for r in P]):.2f} FAIL mean={st.mean([r['gold_n'] for r in F]):.2f}")
pd=sum(1 for r in P if r['has_distractor'])/len(P); fd=sum(1 for r in F if r['has_distractor'])/len(F)
print(f"  has_distractor: PASS {pd:.0%} FAIL {fd:.0%}")
tierF=Counter(r['tier'] for r in F); tierP=Counter(r['tier'] for r in P)
print(f"  tier FAIL={dict(tierF)} PASS={dict(tierP)}")

print(f"\n=== 5. MIX(0.5): does higher-coverage seed pass? ===")
for tid,t in res["templates"].items():
    if t["pass_k"]!=0.5: continue
    gold=set(norm(g) for g in id2task[tid].get("gold_docs",[]))
    covs=[]
    for tr in t["trajectories"]:
        rd=set(traj_reads(tr)); cov=len(rd&gold)/len(gold) if gold else 0
        covs.append(round(cov,2))
    print(f"  {tid}: coverage/traj={covs}")

print(f"\n=== 6. Per-failing-template (gold vs actually read) ===")
for tid,t in res["templates"].items():
    if t["pass_k"]>=1.0: continue
    gold=set(norm(g) for g in id2task[tid].get("gold_docs",[]))
    print(f"  {tid} pk={t['pass_k']} gold({len(gold)})={sorted(gold for old in gold)}")
    for i,tr in enumerate(t["trajectories"]):
        rd=set(traj_reads(tr))
        print(f"     seed{i}: read={sorted(rd)}  hit={len(rd&gold)}/{len(gold)}")
