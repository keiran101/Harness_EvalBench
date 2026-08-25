"""Path-normalized failure classifier. Normalizes \\ -> / and strips ./ before
comparing accessed paths to gold_docs. Reveals how many failures are actually
metric artifacts (backslash paths / bash reads) vs true capability gaps.
"""
import json, os, re, sys
from collections import defaultdict, Counter
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "agent_eval"))
from agent_eval.core import Step, Trajectory
from agent_eval.datasets.registry import DatasetRegistry

RESULTS = {
    "pi": os.path.join(ROOT, "results", "eval_pi_llm_retrieval_20260825_001329.json"),
    "opencode": os.path.join(ROOT, "results", "eval_opencode_retrieval_20260825_003037.json"),
    "deepseek": os.path.join(ROOT, "results", "eval_deepseek_retrieval_20260824_233007.json"),
}
DATA_DIRS = [os.path.join(ROOT, "agent_eval", "agent_eval", "datasets", "data", "retrieval")]
BASH_RD = re.compile(r"\b(cat|tail|head|less|more|sed|awk|grep)\b")


def norm(p):
    return os.path.normpath(p.replace("\\", "/")).replace("\\", "/")


def get_reg():
    return DatasetRegistry.from_dirs(*DATA_DIRS)


def main():
    reg = get_reg()
    cache = {}
    def inst(tid, seed):
        k = (tid, seed)
        if k not in cache:
            cache[k] = reg.instantiate(tid, seed=seed)
        return cache[k]

    out = {}
    for agent, path in RESULTS.items():
        data = json.load(open(path))
        rows = []
        for tid, t in data["templates"].items():
            gold = None
            for seed in (0, 1):
                g = list(getattr(inst(tid, seed), "gold_docs", None) or [])
                if g:
                    gold = g
                    break
            gold_n = set(norm(g) for g in gold)
            for i, tr in enumerate(t["trajectories"]):
                steps = [Step(action=s["action"], observation=s.get("observation", ""),
                              state_before=s.get("state_before", {}), state_after=s.get("state_after", {}),
                              is_error=bool(s.get("is_error", False)), error_category=s.get("error_category"),
                              answer=s.get("answer")) for s in tr.get("steps", [])]
                final_state = steps[-1].state_after if steps else {}
                vr = reg.verify(inst(tid, i if i < 2 else 0), final_state,
                                Trajectory(steps=steps, answer=tr.get("answer")))
                if vr.passed:
                    continue
                read_tool = set()
                bash_read = set()
                used_bash_read = False
                for st in steps:
                    a = st.action
                    if a.split(":", 1)[0] in ("read", "open", "cat"):
                        try:
                            obj = json.loads(a.split(":", 1)[1])
                            if isinstance(obj, dict):
                                for kk in ("path", "file_path", "filePath", "absolute_path"):
                                    if kk in obj and obj[kk]:
                                        read_tool.add(norm(str(obj[kk])))
                            else:
                                read_tool.add(norm(a.split(":", 1)[1].strip()))
                        except Exception:
                            pass
                    elif a.startswith("bash:"):
                        cmd = a.split(":", 1)[1]
                        if BASH_RD.search(cmd):
                            used_bash_read = True
                            for g in gold_n:
                                if os.path.basename(g) in cmd or g in cmd:
                                    bash_read.add(g)
                accessed = read_tool | bash_read
                missed = [g for g in gold if norm(g) not in accessed]
                # cause
                if not accessed:
                    cause = "NO_EXPLORE"
                elif missed == []:
                    cause = "FALSE_NEG (gold accessed via %s)" % (
                        "read-tool+bash" if (read_tool and bash_read) else
                        ("bash" if bash_read else "read-tool"))
                else:
                    cause = "PARTIAL (missed %s)" % missed
                rows.append({"tid": tid, "tier": t["tier"], "seed": i, "cause": cause,
                             "n_steps": len(steps), "missed": missed,
                             "read_tool": sorted(read_tool), "bash": sorted(bash_read)})
        out[agent] = rows
    return out


if __name__ == "__main__":
    rep = main()
    json.dump(rep, open(os.path.join(ROOT, "results", "_failure_causes_norm.json"), "w"),
              ensure_ascii=False, indent=2)
    for agent, rows in rep.items():
        print("=" * 60, agent, "failing seeds:", len(rows))
        cats = Counter(r["cause"].split(" ")[0] for r in rows)
        for c, n in cats.most_common():
            print(f"  {c}: {n}")
        # breakdown by tier of false-neg vs true
        fn = sum(1 for r in rows if r["cause"].startswith("FALSE_NEG"))
        part = sum(1 for r in rows if r["cause"].startswith("PARTIAL"))
        noe = sum(1 for r in rows if r["cause"] == "NO_EXPLORE")
        print(f"  >> false_neg={fn}  partial={part}  no_explore(real)={noe}")
