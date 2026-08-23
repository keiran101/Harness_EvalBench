"""Zero-dependency end-to-end demo (design doc §9 steps 2-3).

Evaluates three mock agents (reference / flaky / buggy) on the base-tier dataset
and writes `eval_output.json`. No API key, no network.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_eval.agents import BuggyAgent, FlakyAgent, ReferenceAgent
from agent_eval.datasets.registry import DatasetRegistry
from agent_eval.evaluator import Evaluator


def main() -> None:
    reg = DatasetRegistry.with_base()
    tids = [t.id for t in reg.list_templates()]
    out = {"k": 4, "registry_version": reg.version, "agents": {}}

    for agent in (ReferenceAgent(), FlakyAgent(fail_every=4), BuggyAgent()):
        ev = Evaluator(reg, agent, k=4, seed_base=0)
        out["agents"][agent.name] = ev.evaluate(tids=tids)

    # Compact console table
    print(f"{'agent':>10} | {'Pass@k':>6} {'Pass^k':>6} {'Pass^k(strict)':>14} {'first_err':>9}")
    for name, s in out["agents"].items():
        o = s["overall"]
        print(f"{name:>10} | {o['pass_at_k']:6.2f} {o['pass_k']:6.2f} "
              f"{o['pass_consecutive_k']:14.2f} {o['first_error_cases']:9d}")

    out_path = os.path.join(os.path.dirname(__file__), "..", "eval_output.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("written:", os.path.abspath(out_path))


if __name__ == "__main__":
    main()
