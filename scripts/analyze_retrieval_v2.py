"""Refined retrieval analysis: separate TRUE capability failures from
coverage-metric false negatives (agent read gold via bash cat/tail/head,
which the coverage metric does not count because it only sees the read/open/cat TOOLS).
"""
import json, os, re, sys
from collections import defaultdict
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


def get_reg():
    return DatasetRegistry.from_dirs(*DATA_DIRS)


def accessed_via_bash(cmd, gold):
    """Return list of gold files referenced by a bash read command."""
    hit = []
    # crude: normalize path separators, look for the gold basename / full path
    for g in gold:
        base = os.path.basename(g)
        if base in cmd or g in cmd:
            hit.append(g)
    return hit


def main():
    reg = get_reg()
    cache = {}
    def inst(tid, seed):
        k = (tid, seed)
        if k not in cache:
            cache[k] = reg.instantiate(tid, seed=seed)
        return cache[k]

    report = {}
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
                # classify
                read_tool_viewed = set()
                bash_viewed = set()
                no_explore = True
                for st in steps:
                    a = st.action
                    if a.startswith("read:") or a.startswith("open:") or a.startswith("cat:"):
                        try:
                            obj = json.loads(a.split(":", 1)[1])
                            if isinstance(obj, dict):
                                for kk in ("path", "file_path", "filePath", "absolute_path"):
                                    if kk in obj and obj[kk]:
                                        read_tool_viewed.add(str(obj[kk]))
                            else:
                                read_tool_viewed.add(a.split(":", 1)[1].strip())
                        except Exception:
                            pass
                    elif a.startswith("bash:"):
                        cmd = a.split(":", 1)[1]
                        if BASH_RD.search(cmd):
                            no_explore = False
                            for g in gold:
                                if os.path.basename(g) in cmd or g in cmd:
                                    bash_viewed.add(g)
                missed_gold = [g for g in gold if g not in (read_tool_viewed | bash_viewed)]
                # decision
                if missed_gold == []:
                    cause = "METRIC_FALSE_NEG (read gold via bash, not read-tool)"
                elif bash_viewed and missed_gold:
                    cause = "PARTIAL (read some gold via bash, missed %s)" % missed_gold
                elif not no_explore and not bash_viewed and not read_tool_viewed:
                    cause = "EXPLORATION_FAILED (ran commands but touched no gold)"
                else:
                    cause = "NO_EXPLORE (no file read at all)"
                rows.append({
                    "tid": tid, "tier": t["tier"], "seed": i,
                    "cause": cause, "missed": missed_gold,
                    "read_tool": sorted(read_tool_viewed), "bash": sorted(bash_viewed),
                    "n_steps": len(steps),
                })
        report[agent] = rows
    return report


if __name__ == "__main__":
    rep = main()
    json.dump(rep, open(os.path.join(ROOT, "results", "_failure_causes.json"), "w"),
              ensure_ascii=False, indent=2)
    for agent, rows in rep.items():
        print("=" * 60, agent, "failing seeds:", len(rows))
        cats = defaultdict(list)
        for r in rows:
            cats[r["cause"].split(" ")[0]].append(r["tid"] + "#" + str(r["seed"]))
        for c, items in cats.items():
            print(f"  {c}: {len(items)}  {items}")
