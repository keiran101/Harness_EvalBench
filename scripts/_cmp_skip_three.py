import json
files={"deepseek":"results/eval_deepseek_retrieval_keycases_20260825_203404.json",
 "pi":"results/eval_pi_llm_retrieval_keycases_20260825_211740.json",
 "opencode":"results/eval_opencode_retrieval_keycases_20260825_213556.json"}
data={n:json.load(open(f,encoding="utf-8")) for n,f in files.items()}
READ_TOOLS={"read","open","cat","view","show"}
DISCOVERY={"glob","ls","find","search","tree","fd","rg"}
BASH_READ={"cat","tail","head","less","more","nl","type","bat","Get-Content","gc","sls","Select-String"}
def cls(a):
    if ":" not in a: return "other"
    t,arg=a.split(":",1); t=t.strip()
    if t in READ_TOOLS: return "read"
    if t in DISCOVERY: return "disc"
    if t in ("bash","sh","pwsh","powershell","cmd","shell"):
        return "read" if any(b.lower() in arg.lower() for b in BASH_READ) else "other"
    return "other"
for a in data:
    tpl=data[a]["templates"]
    def skip_rate(sub):
        n=len(sub); s=sum(1 for tid in sub for tr in tpl[tid]["trajectories"] if not any(cls(s2["action"])=="read" for s2 in tr["steps"]))
        return s,n
    allt=list(tpl); kc=[t for t in allt if "keycases" in t]; nk=[t for t in allt if "keycases" not in t]
    sa,na=skip_rate(allt); sk,nk2=skip_rate(kc); sn,nn=skip_rate(nk)
    print(f"{a:9}: overall skip={sa}/{na}={sa/na:.0%} | keycases skip={sk}/{nk2}={sk/nk2:.0%} | non-keycases skip={sn}/{nn}={sn/nn:.0%}")
