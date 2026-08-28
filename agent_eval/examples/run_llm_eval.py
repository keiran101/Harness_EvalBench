"""Real-LLM agent evaluation entrypoint.

Runs the base-tier dataset against a REAL LLM agent (function-calling loop over
the env tools) served by an OpenAI-compatible endpoint, with a real LLM judge.
Verification stays environment-state based (design doc §3 / §8.1).

Usage:
    python examples/run_llm_eval.py --k 3 [--smoke] [--tids id1,id2]
Env: LLM_EVAL_BASE_URL (default http://8.134.63.180:7010), LLM_EVAL_MODEL
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_eval.datasets.registry import DatasetRegistry
from agent_eval.evaluator import Evaluator
from agent_eval.llm_agent import LLMToolAgent, RealLLMJudge
from agent_eval.metrics.metrics import summarize


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--smoke", action="store_true", help="run 1 template x 1 sample")
    ap.add_argument("--tids", type=str, default="")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--out", type=str, default="eval_llm_output.json")
    ap.add_argument("--judge", type=str, choices=["dummy", "llm"], default="dummy",
                    help="dummy=rule-based (fast, default); llm=real LLM judge (slow)")
    args = ap.parse_args()

    reg = DatasetRegistry.from_dir(
        os.path.join(os.path.dirname(__file__), "..", "data", "base"))
    tids = [t.id for t in reg.list_templates()]
    if args.tids:
        keep = {x.strip() for x in args.tids.split(",") if x.strip()}
        tids = [t for t in tids if t in keep]
    if args.smoke:
        tids, k = tids[:1], 1
    else:
        k = args.k

    agent = LLMToolAgent(verbose=args.verbose)
    judge = RealLLMJudge(verbose=args.verbose) if args.judge == "llm" else None
    ev = Evaluator(reg, agent, k=k, seed_base=0, judge=judge)

    print(f"== Real-LLM eval: {len(tids)} templates x k={k} ==")
    print(f"   agent={agent.name}  judge={judge.name if judge else 'dummy'}")
    t0 = time.time()
    summary = ev.evaluate(tids=tids)
    dt = time.time() - t0

    o = summary["overall"]
    print("\n" + "=" * 60)
    print(f"{'agent':>18} | {'Pass@k':>6} {'Pass^k':>6} {'Pass^k(strict)':>14} {'first_err':>9}")
    print(f"{agent.name:>18} | {o['pass_at_k']:6.2f} {o['pass_k']:6.2f} "
          f"{o['pass_consecutive_k']:14.2f} {o['first_error_cases']:9d}")
    print(f"elapsed: {dt:.0f}s  ({(dt / max(len(tids) * k, 1)):.1f}s/episode)")

    print("\n-- per template --")
    print(f"{'template':>24} | {'Pass@k':>6} {'Pass^k':>6} | judge(mean)")
    for tid, t in summary["templates"].items():
        print(f"{tid:>24} | {t['pass_at_k']:6.2f} {t['pass_k']:6.2f} |")

    out_path = os.path.join(os.path.dirname(__file__), "..", args.out)
    summary["_meta"] = {
        "agent": agent.name,
        "agent_type": "llm",
        "strategy": None,
        "model": agent.model,
        "judge": judge.name if judge else "dummy-verifier",
        "verifier": "deterministic-env-state",
        "dataset_scope": ["base"],
        "templates_run": len(tids),
        "k": k,
        "seed_base": 0,
        "sample_size": len(tids) * k,
        "elapsed_s": round(dt, 1),
        "base_url": os.environ.get("LLM_EVAL_BASE_URL", "http://8.134.63.180:7010"),
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print("\nwritten:", os.path.abspath(out_path))


if __name__ == "__main__":
    main()
