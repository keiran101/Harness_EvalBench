import json, statistics as st

f = "results/eval_deepseek_retrieval_keycases_20260825_203404.json"
d = json.load(open(f, encoding="utf-8"))

READ = {"read","open","cat","view","show","type","less","more","nl","bat","Get-Content","gc","sls","Select-String","head","tail"}
DISCOVERY = {"glob","ls","find","search","tree","fd","rg","grep"}

def classify(action):
    if ":" not in action:
        return "other"
    tool = action.split(":",1)[0].strip()
    if tool in READ: return "read"
    if tool in DISCOVERY: return "discover"
    if tool in ("bash","sh","shell","cmd"):
        low = action.lower()
        if any(b in low for b in ("cat ","head ","tail ","type ","less ","nl ","get-content","sls")):
            return "read"
        return "other"
    return "other"

def feats(tr):
    steps = tr.get("steps", [])
    n = len(steps)
    reads = sum(1 for s in steps if classify(s["action"])=="read")
    disc = sum(1 for s in steps if classify(s["action"])=="discover")
    errs = [s for s in steps if s.get("is_error")]
    # env file count from first step state_before
    env = 0
    if steps and isinstance(steps[0].get("state_before"), dict):
        env = len(steps[0]["state_before"])
    lat = tr.get("latency_ms") or 0
    return dict(n=n, reads=reads, disc=disc, nerr=len(errs),
               errcats=[s.get("error_category") for s in errs], env=env, lat=lat)

# build per-template rows
rows = []
for tid, t in d["templates"].items():
    pk = t["pass_k"]
    trajs = t["trajectories"]
    fts = [feats(tr) for tr in trajs]
    env0 = fts[0]["env"]
    rows.append(dict(
        tid=tid, tier=t["tier"], pk=pk,
        env=env0,
        mean_steps=st.mean([x["n"] for x in fts]),
        mean_reads=st.mean([x["reads"] for x in fts]),
        mean_disc=st.mean([x["disc"] for x in fts]),
        mean_err=st.mean([x["nerr"] for x in fts]),
        mean_lat=st.mean([x["lat"] for x in fts]),
        any0read = any(x["reads"]==0 for x in fts),
    ))

# Group labels: PASS (pk==1.0) full-pass; FAIL (pk==0.0) full-fail
PASS = [r for r in rows if r["pk"]==1.0]
FAIL = [r for r in rows if r["pk"]==0.0]
MIX  = [r for r in rows if r["pk"]==0.5]
print(f"Templates: total={len(rows)} PASS={len(PASS)} FAIL={len(FAIL)} MIX(0.5)={len(MIX)}")
print(f"Trajectories (labeled): PASS={len(PASS)*2} FAIL={len(FAIL)*2}")

def cmp(key, label):
    pv = [r[key] for r in PASS]
    fv = [r[key] for r in FAIL]
    print(f"\n[{label}]  PASS mean={st.mean(pv):.3f}  FAIL mean={st.mean(fv):.3f}  (delta={st.mean(fv)-st.mean(pv):+.3f})")
    # fraction of templates with 0 reads
    if key=="any0read":
        print(f"    PASS templates w/ a 0-read traj: {sum(pv)}/{len(pv)} = {st.mean([1 if x else 0 for x in pv]):.0%}")
        print(f"    FAIL templates w/ a 0-read traj: {sum(fv)}/{len(fv)} = {st.mean([1 if x else 0 for x in fv]):.0%}")

print("\n================ A. PASS vs FAIL: feature means ================")
cmp("mean_reads","reads/traj")
cmp("mean_disc","discovery/traj")
cmp("mean_steps","steps/traj")
cmp("mean_err","errors/traj")
cmp("env","env file count")
cmp("mean_lat","latency ms")
cmp("any0read","any-traj-0-read (flag)")

print("\n================ B. 0-READ shortcut rate ================")
# per-trajectory level for PASS/FAIL
def traj_groups():
    p, fl = [], []
    for r in rows:
        for tr in d["templates"][r["tid"]]["trajectories"]:
            x = feats(tr)
            if r["pk"]==1.0: p.append(x)
            elif r["pk"]==0.0: fl.append(x)
    return p, fl
P, F = traj_groups()
print(f"PASS trajs: {len(P)},  of which 0-read = {sum(1 for x in P if x['reads']==0)} ({sum(1 for x in P if x['reads']==0)/len(P):.0%})")
print(f"FAIL trajs: {len(F)},  of which 0-read = {sum(1 for x in F if x['reads']==0)} ({sum(1 for x in F if x['reads']==0)/len(F):.0%})")
# among non-zero-read FAIL, how many read but still fail
f_read = [x for x in F if x["reads"]>0]
p_read = [x for x in P if x["reads"]>0]
print(f"\nAmong FAIL that DID read (n={len(f_read)}):")
print(f"   mean reads={st.mean([x['reads'] for x in f_read]):.2f}, mean steps={st.mean([x['n'] for x in f_read]):.2f}, mean errs={st.mean([x['nerr'] for x in f_read]):.2f}")
print(f"   error categories present: {sorted(set(c for x in f_read for c in x['errcats'] if c))}")
print(f"Among PASS that DID read (n={len(p_read)}):")
print(f"   mean reads={st.mean([x['reads'] for x in p_read]):.2f}, mean steps={st.mean([x['n'] for x in p_read]):.2f}, mean errs={st.mean([x['nerr'] for x in p_read]):.2f}")

print("\n================ C. failure by TIER ================")
from collections import Counter, defaultdict
tier_fail = Counter(r["tier"] for r in FAIL)
tier_pass = Counter(r["tier"] for r in PASS)
tier_all = Counter(r["tier"] for r in rows)
print("tier | FAIL/ALL | fail-rate")
for tier in ["base","middle","hard"]:
    fa=tier_fail.get(tier,0); al=tier_all.get(tier,0)
    print(f"  {tier:7} | {fa}/{al} | {fa/al:.0%}")

print("\n================ D. env file count vs outcome ================")
# bucket env size
def bucket(e):
    if e<=3: return "1-3"
    if e<=6: return "4-6"
    if e<=10: return "7-10"
    return "11+"
eb = defaultdict(lambda:[0,0])
for r in rows:
    b=bucket(r["env"])
    eb[b][0]+= (r["pk"]==0.0)  # fails
    eb[b][1]+= 1
print("env-bucket | fails/all | fail-rate")
for b in ["1-3","4-6","7-10","11+"]:
    if b in eb:
        fa,al=eb[b]
        print(f"  {b:7} | {fa}/{al} | {fa/al:.0%}")

print("\n================ E. MIX (0.5) templates detail ================")
for r in MIX:
    t=d["templates"][r["tid"]]
    line=f"  {r['tid']} tier={r['tier']} env={r['env']} reads/traj={[feats(tr)['reads'] for tr in t['trajectories']]}"
    print(line)
