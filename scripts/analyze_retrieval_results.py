"""Analyze the 3-agent retrieval LLM eval results with trajectory-based attribution.

Re-runs the deterministic verifier on every captured trajectory so we get the TRUE
per-trajectory pass and which fail_to_pass / pass_to_pass / must_not_do checks failed,
then attributes failures to concrete causes (missed gold doc, illegal action, corrupted
file, etc.) using the stored steps.
"""
import json, os, sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "agent_eval"))
from agent_eval.core import Step, Trajectory
from agent_eval.datasets.registry import DatasetRegistry
from agent_eval.metrics.process import _read_path, READ_TOOLS, _tool_of

RESULTS = {
    "pi": os.path.join(ROOT, "results", "eval_pi_llm_retrieval_20260825_001329.json"),
    "opencode": os.path.join(ROOT, "results", "eval_opencode_retrieval_20260825_003037.json"),
    "deepseek": os.path.join(ROOT, "results", "eval_deepseek_retrieval_20260824_233007.json"),
}
DATA_DIRS = [os.path.join(ROOT, "agent_eval", "agent_eval", "datasets", "data", "retrieval")]


def build_registry():
    return DatasetRegistry.from_dirs(*DATA_DIRS)


def read_paths_of(traj_obj):
    viewed = []
    for st in traj_obj.steps:
        if _tool_of(st.action) in READ_TOOLS:
            p = _read_path(st.action)
            if p:
                viewed.append(p)
    return viewed


def reconstruct(traj_dict):
    steps = [Step(action=s["action"], observation=s.get("observation", ""),
                  state_before=s.get("state_before", {}), state_after=s.get("state_after", {}),
                  is_error=bool(s.get("is_error", False)), error_category=s.get("error_category"),
                  answer=s.get("answer")) for s in traj_dict.get("steps", [])]
    final_state = steps[-1].state_after if steps else {}
    return Trajectory(steps=steps, answer=traj_dict.get("answer"),
                      latency_ms=traj_dict.get("latency_ms"),
                      request_count=traj_dict.get("request_count")), final_state


def main():
    reg = build_registry()
    # per-instance metadata: gold_docs + tier
    inst_cache = {}
    def get_inst(tid, seed):
        key = (tid, seed)
        if key not in inst_cache:
            inst_cache[key] = reg.instantiate(tid, seed=seed)
        return inst_cache[key]

    out = {}
    for agent, path in RESULTS.items():
        data = json.load(open(path))
        per_tmpl = data["templates"]
        rows = []
        for tid, t in per_tmpl.items():
            gold = None
            for seed in (0, 1):
                inst = get_inst(tid, seed)
                gold = list(getattr(inst, "gold_docs", None) or [])
                if gold:
                    break
            traj_records = t.get("trajectories", [])
            per_seed = []
            for i, tr in enumerate(traj_records):
                traj_obj, final_state = reconstruct(tr)
                inst = get_inst(tid, seed=i if i < 2 else 0)
                vr = reg.verify(inst, final_state, traj_obj)
                viewed = read_paths_of(traj_obj)
                cov = round(len([g for g in gold if g in viewed]) / len(gold), 4) if gold else None
                missed = [g for g in gold if g not in viewed] if gold else []
                # illegal actions
                illegal = [st.action for st in traj_obj.steps if st.is_error]
                per_seed.append({
                    "seed": i,
                    "passed": vr.passed,
                    "fail_to_pass": vr.fail_to_pass,
                    "pass_to_pass": vr.pass_to_pass,
                    "must_not_do": vr.must_not_do,
                    "coverage": cov,
                    "missed_gold": missed,
                    "viewed": viewed,
                    "illegal": illegal,
                    "n_steps": len(traj_obj.steps),
                })
            fails = [s for s in per_seed if not s["passed"]]
            rows.append({
                "tid": tid, "tier": t["tier"],
                "pass_k": t["pass_k"], "pass_at_k": t["pass_at_k"],
                "n_fail": len(fails), "seeds": per_seed,
            })
        # summary by tier
        by_tier = defaultdict(lambda: {"n": 0, "pass": 0, "fail_tids": []})
        for r in rows:
            bt = by_tier[r["tier"]]
            bt["n"] += 1
            if r["pass_k"] == 1.0:
                bt["pass"] += 1
            else:
                bt["fail_tids"].append(r["tid"])
        out[agent] = {"overall": data["overall"], "process_metrics": data.get("process_metrics"),
                      "rows": rows, "by_tier": {k: dict(v) for k, v in by_tier.items()}}
    return out


if __name__ == "__main__":
    out = main()
    json.dump(out, open(os.path.join(ROOT, "results", "_analysis_intermediate.json"), "w"),
              ensure_ascii=False, indent=2)
    # console summary
    for agent, a in out.items():
        print("="*70)
        print(agent, "overall:", {k: round(v,4) if isinstance(v,float) else v for k,v in a["overall"].items()})
        print("by_tier (n_pass/n_total, fail_tids):")
        for tier, bt in a["by_tier"].items():
            print(f"  {tier}: {bt['pass']}/{bt['n']}  fails={bt['fail_tids']}")
        fails = [r for r in a["rows"] if r["n_fail"]>0]
        print(f"failing templates: {len(fails)}")
