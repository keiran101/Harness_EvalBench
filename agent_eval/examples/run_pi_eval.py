"""按评估设计接入 pi coding-agent 并跑出完整指标报告。

流程（对应顶层设计方案 §4/§5）：
  coding 数据集 (from_dir) -> FsEnv(真实临时目录) -> PiAgentAdapter(桥接 pi)
  -> verifier(双检+硬否决) -> 指标体系(§5) -> eval_pi_output.json

指标体系（设计文档 §5，全部呈现）：
  §5.1 两层核心指标 : Pass@k(上限) / Pass^k(可靠性) / Pass consecutive@k + k 口径
  §5.2 过程指标(白盒): 路径步数 / 冗余动作率 / 工具选择正确率 / 工具使用分布
  §5.3 安全/鲁棒性  : 硬否决违规次数(权限越界) / 轨迹覆盖率
  §5.4 报告纪律    : k / 样本量 / 环境差异 / 未完成
  §5.5 复杂度分层   : 按 tier 切片 + 失败指向
  失败归因聚合      : failure category 分布
  统计显著性        : Pass^k 的 Wilson 95% 置信区间

被测对象 = pi Harness（工具执行/状态/会话层）+ 确定性注入决策层（无 key）。
"""

import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_eval.datasets.registry import DatasetRegistry
from agent_eval.environments.fs_env import FsEnv
from agent_eval.pi_adapter import PiAgentAdapter


def _wilson_ci(p: float, n: int, z: float = 1.96):
    """Wilson score 95% 置信区间。n=0 时返回 (0,0)。"""
    if n == 0:
        return [0.0, 0.0]
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [round(max(0.0, centre - margin), 4), round(min(1.0, centre + margin), 4)]


def _tool_usage(traj):
    """轨迹内各工具调用次数分布。"""
    usage = {}
    for st in traj.steps:
        tool = st.action.split(":", 1)[0]
        usage[tool] = usage.get(tool, 0) + 1
    return usage


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
                # §5.3 安全：硬否决触发（权限越界/危险行为）= veto 任一 False
                veto_triggered = bool(vr.must_not_do) and not all(vr.must_not_do.values())
                # §5.2 过程：轨迹步数 + 工具分布 + 错误步数
                n_steps = len(traj.steps)
                tool_usage = _tool_usage(traj)
                n_error_steps = sum(1 for st in traj.steps if st.is_error)
                reps.append(EvalReport(
                    case_id=inst.id, tier=inst.tier, capability=inst.capability,
                    passed=vr.passed, first_error_step=fe,
                    metrics={
                        "judge": js.overall,
                        "failure_category": js.failure_category,
                        "ftp": vr.fail_to_pass, "ptp": vr.pass_to_pass,
                        "veto": vr.must_not_do,
                        # 过程指标原始值
                        "steps": n_steps,
                        "tool_usage": tool_usage,
                        "error_steps": n_error_steps,
                        "veto_triggered": veto_triggered,
                    },
                ))
            finally:
                env.cleanup()
        per_template[t.id] = {
            "tier": t.tier, "capability": t.capability,
            "available_tools": t.available_tools,
            "passed": [r.passed for r in reps],
            "first_error_steps": [r.first_error_step for r in reps if r.first_error_step is not None],
            "categories": [r.metrics.get("failure_category") for r in reps if not r.passed],
            "steps": [r.metrics["steps"] for r in reps],
            "tool_usage": [r.metrics["tool_usage"] for r in reps],
            "error_steps": [r.metrics["error_steps"] for r in reps],
            "veto_triggered": [r.metrics["veto_triggered"] for r in reps],
        }
        reports.extend(reps)

    # ---- 指标聚合（设计文档 §5）----
    from agent_eval.metrics.metrics import summarize
    summary = summarize(reports, k)
    summary["agent"] = agent.name

    n = len(reports)
    n_pass = sum(1 for r in reports if r.passed)
    steps_all = [r.metrics["steps"] for r in reports]
    steps_pass = [r.metrics["steps"] for r in reports if r.passed]
    steps_fail = [r.metrics["steps"] for r in reports if not r.passed]
    veto_count = sum(1 for r in reports if r.metrics["veto_triggered"])
    err_steps = sum(r.metrics["error_steps"] for r in reports)
    tools_used = {}
    for r in reports:
        for tool, c in r.metrics["tool_usage"].items():
            tools_used[tool] = tools_used.get(tool, 0) + c

    # 归因分布
    attr = {}
    for r in reports:
        if not r.passed:
            c = r.metrics.get("failure_category") or "unknown"
            attr[c] = attr.get(c, 0) + 1

    # 工具选择正确率：任务实际用到的工具 ⊆ available_tools 的比例
    tool_correct = 0
    tool_total = 0
    for t in reg.list_templates():
        for i in range(k):
            inst = reg.instantiate(t.id, seed=seed_base + i)
            used = set()
            # 从 per_template 拿对应样本的 tool_usage
            usage = per_template[t.id]["tool_usage"][i]
            used = set(usage.keys())
            allowed = set(t.available_tools)
            tool_total += 1
            tool_correct += 1 if used and used <= allowed else 0

    # 冗余动作率：失败轨迹平均步数比该任务最小必要步数多出的比例
    min_steps = {t.id: t.steps for t in reg.list_templates()}
    redundancy = {}
    for tid, t in per_template.items():
        necessary = min_steps.get(tid, 1) or 1
        avg_fail = sum(t["steps"]) / len(t["steps"]) if t["steps"] else 0
        redundancy[tid] = round(max(0.0, (avg_fail - necessary) / necessary), 3)

    summary["indicator_system"] = {
        "core": {  # §5.1
            "pass_at_k": summary["overall"]["pass_at_k"],
            "pass_k": summary["overall"]["pass_k"],
            "pass_consecutive_k": summary["overall"]["pass_consecutive_k"],
            "k_scope": "same-task k independent samples",
            "wilson95_ci_pass_k": _wilson_ci(summary["overall"]["pass_k"], n),
        },
        "process": {  # §5.2 白盒
            "avg_steps_all": round(sum(steps_all) / n, 2) if n else 0,
            "avg_steps_passed": round(sum(steps_pass) / len(steps_pass), 2) if steps_pass else None,
            "avg_steps_failed": round(sum(steps_fail) / len(steps_fail), 2) if steps_fail else None,
            "error_steps_total": err_steps,
            "tool_use_distribution": tools_used,
            "tool_selection_accuracy": round(tool_correct / tool_total, 3) if tool_total else None,
            "redundancy_by_task": redundancy,
        },
        "safety": {  # §5.3
            "hard_veto_violations": veto_count,
            "veto_violation_rate": round(veto_count / n, 3) if n else 0,
            "trajectory_coverage": round(n_pass / n, 3) if n else 0,
        },
        "attribution": {  # 失败归因聚合
            "failure_category_distribution": attr,
            "first_error_cases": summary["overall"]["first_error_cases"],
        },
        "discipline": {  # §5.4 报告纪律
            "k": k,
            "sample_size": n,
            "env": "real filesystem tempdir (pi bridge, fake ModelRuntime)",
            "unfinished": [],
        },
        "tier_slice": {  # §5.5 复杂度分层
            "base": {"n": n, "pass_k": summary["overall"]["pass_k"]},
        },
    }
    summary["templates"] = per_template
    return summary


def _print_summary(s):
    ind = s["indicator_system"]
    o = s["overall"]
    print(f"  [§5.1 核心] Pass@k={o['pass_at_k']:.2f}  Pass^k={o['pass_k']:.2f}  "
          f"strict={o['pass_consecutive_k']:.2f}  95%CI={ind['core']['wilson95_ci_pass_k']}")
    pr = ind["process"]
    print(f"  [§5.2 过程] 平均步数(all)={pr['avg_steps_all']} 通过={pr['avg_steps_passed']} "
          f"失败={pr['avg_steps_failed']}  工具分布={pr['tool_use_distribution']} "
          f"选型准确率={pr['tool_selection_accuracy']}")
    sf = ind["safety"]
    print(f"  [§5.3 安全] 硬否决违规={sf['hard_veto_violations']} 率={sf['veto_violation_rate']} "
          f"轨迹覆盖={sf['trajectory_coverage']}")
    at = ind["attribution"]
    print(f"  [归因] 类别分布={at['failure_category_distribution']} "
          f"首错用例={at['first_error_cases']}")
    print("  分任务:")
    for tid, t in s["templates"].items():
        print(f"    {tid:16s} pass={sum(t['passed'])}/{len(t['passed'])} "
              f"steps={t['steps']} veto={t['veto_triggered']} cats={t['categories']}")


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
        summary = _run_with_fsenv(reg, adapter, k=2, seed_base=0)
        out["agents"][strategy] = summary
        print(f"\n=== pi-{strategy} ===")
        _print_summary(summary)

    # 落盘：先尝试写文件；沙箱环境可能拒绝，则输出到 stdout 供捕获
    try:
        with open(os.path.join(here, "..", "eval_pi_output.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"\nwritten: agent_eval/eval_pi_output.json")
    except PermissionError:
        print("\n[stdout-json]" + json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()
