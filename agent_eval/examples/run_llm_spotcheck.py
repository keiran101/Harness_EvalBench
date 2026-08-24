"""Sample-level spot check: re-run selected templates with real LLM judge.

Shows the actual trajectories (proving behavior is real, not lucky) and scores
them with the real LLM judge. Serial, low load: 6 cases x (agent loop + judge).
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_eval.datasets.registry import DatasetRegistry
from agent_eval.environments.env import Env
from agent_eval.llm_agent import LLMToolAgent, RealLLMJudge

BASE = os.path.join(os.path.dirname(__file__), "..", "agent_eval", "datasets", "data", "base")
TIDS = ["base_tool_call_001", "base_state_read_001", "base_error_recovery_001",
        "base_clarify_001", "base_confirm_001", "base_confirm_002"]

reg = DatasetRegistry.from_dir(BASE)
agent = LLMToolAgent()
judge = RealLLMJudge()
out = []
t0 = time.time()

for tid in TIDS:
    inst = reg.instantiate(tid, seed=0)
    env = Env(inst.setup, backend=(inst.env or {}).get("backend", "memory"))
    traj = agent.run(inst, env)
    final = env.get_state()
    vr = reg.verify(inst, final, traj)
    js = judge.score(inst, traj, final, vr)
    entry = {
        "template": tid,
        "instruction": inst.instruction,
        "passed": vr.passed,
        "verifier": {"fail_to_pass": vr.fail_to_pass, "pass_to_pass": vr.pass_to_pass,
                     "must_not_do": vr.must_not_do},
        "trajectory": [{"action": s.action, "is_error": s.is_error,
                        "obs": s.observation} for s in traj.steps],
        "answer": traj.answer,
        "judge": {"overall": js.overall, "rubric": js.rubric_scores,
                  "failure_category": js.failure_category},
    }
    out.append(entry)
    print("=" * 72)
    print(f"[{tid}] passed={vr.passed}  judge={js.overall:.2f} {js.rubric_scores}")
    for s in traj.steps:
        flag = "!!" if s.is_error else "  "
        print(f"  {flag} {s.action:<28} -> {s.observation[:90]}")
    print(f"  answer: {traj.answer}")
    env.cleanup()

print("\nelapsed:", round(time.time() - t0, 1), "s")
with open(os.path.join(os.path.dirname(__file__), "..", "eval_llm_spotcheck.json"),
          "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print("written: eval_llm_spotcheck.json")
