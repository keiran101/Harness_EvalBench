"""按评估设计接入 pi coding-agent 并跑出指标报告。

流程（对应顶层设计方案）：
  coding 数据集 (from_dir) -> FsEnv(真实临时目录) -> PiAgentAdapter(桥接 pi)
  -> verifier(双检+硬否决) -> metrics(Pass@k/Pass^k/归因) -> eval_pi_output.json

被测对象 = pi Harness（工具执行/状态/会话层）+ 确定性注入决策层（无 key）。
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_eval.datasets.registry import DatasetRegistry
from agent_eval.environments.fs_env import FsEnv
from agent_eval.evaluator import Evaluator
from agent_eval.pi_adapter import PiAgentAdapter


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(here, "..", "agent_eval", "datasets", "data", "coding")
    reg = DatasetRegistry.from_dir(data_dir, version="coding-0.1")

    print(f"coding 数据集: {len(reg.list_templates())} 个任务")
    for t in reg.list_templates():
        print(f"  - {t.id:16s} caps={t.capability} diff={t.difficulty}")

    out = {"dataset": "coding", "version": reg.version, "agents": {}}
    for strategy in ("reference", "buggy"):
        adapter = PiAgentAdapter(strategy=strategy)
        ev = Evaluator(reg, adapter, k=2, seed_base=0)
        # Evaluator 用 ToolCallingEnv；这里要换成 FsEnv —— 直接跑 run_case 手动编排
        summary = _run_with_fsenv(reg, adapter, k=2, seed_base=0)
        out["agents"][strategy] = summary
        print(f"\n=== pi-{strategy} ===")
        _print_summary(summary)

    with open(os.path.join(here, "..", "eval_pi_output.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\nwritten: agent_eval/eval_pi_output.json")


def _run_with_fsenv(reg, agent, k, seed_base):
    """手动编排：instance -> FsEnv -> agent(pi bridge) -> verify -> report."""
    from agent_eval.core import EvalReport, first_error_step
    from agent_eval.judge.judge import DummyJudge

    judge = DummyJudge()
    reports, per_template = [], {}
    for t in reg.list_templates():
        reps = []
        for i in range(k):
            inst = reg.instantiate(t.id, seed=seed_base + i)
            env = FsEnv(inst.setup)
            try:
                traj = agent.run(inst, env)
                final_state = env.get_state()
                vr = reg.verify(inst, final_state, traj)
                js = judge.score(inst, traj, final_state, vr)
                fe = first_error_step(traj) if not vr.passed else None
                reps.append(EvalReport(
                    case_id=inst.id, tier=inst.tier, capability=inst.capability,
                    passed=vr.passed, first_error_step=fe,
                    metrics={"judge": js.overall,
                             "failure_category": js.failure_category,
                             "ftp": vr.fail_to_pass, "ptp": vr.pass_to_pass,
                             "veto": vr.must_not_do},
                ))
            finally:
                env.cleanup()
        per_template[t.id] = {
            "tier": t.tier, "capability": t.capability,
            "passed": [r.passed for r in reps],
            "first_error_steps": [r.first_error_step for r in reps if r.first_error_step is not None],
            "categories": [r.metrics.get("failure_category") for r in reps if not r.passed],
        }
        reports.extend(reps)
    from agent_eval.metrics.metrics import summarize
    summary = summarize(reports, k)
    summary["agent"] = agent.name
    summary["templates"] = per_template
    return summary


def _print_summary(s):
    o = s["overall"]
    print(f"  Pass@k={o['pass_at_k']:.2f}  Pass^k={o['pass_k']:.2f}  "
          f"Pass^k(strict)={o['pass_consecutive_k']:.2f}  first_err_cases={o['first_error_cases']}")
    print("  分任务:")
    for tid, t in s["templates"].items():
        print(f"    {tid:16s} pass={sum(t['passed'])}/{len(t['passed'])}  "
              f"cats={t['categories']}")


if __name__ == "__main__":
    main()
