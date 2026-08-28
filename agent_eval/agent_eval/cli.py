"""Official evaluation CLI — the single entry point for running evals.

Unified architecture (2026-08-23):
  datasets FILE-ISOLATED (data/biz, data/coding, ...) merged into ONE pool
  evaluation NEVER splits by domain: one Evaluator + one env_factory, backend picked
  per-instance from the dataset's `env.backend` field
  agents plug in uniformly: `mock` (in-process perfect executor) or `pi` (real pi
  coding-agent via the TS bridge, data-driven reference_plan)

Usage:
  python -m agent_eval --agent mock [--datasets biz,coding] [--k 4]
  python -m agent_eval --agent llm --datasets biz --k 2 [--tids base_tool_call_001]
  python -m agent_eval --agent pi --strategy reference --k 2
  python -m agent_eval --agent pi --strategy buggy  --k 2 --output eval_pi_buggy.json

Agent scope (auto-filtered by backend, mirrored in _meta.agent_type):
  mock  -> every template in the merged pool
  llm   -> memory-backed templates only (real-LLM tool surface = memory 6 tools)
  pi    -> disk-backed templates only (coding agent)
Every output file carries a uniform _meta block (agent/agent_type/model/judge/
dataset_scope/k/sample_size) so runs from different agents can never be mixed up.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from typing import List, Optional

from .agents import UnifiedMockAgent
from .datasets.registry import DatasetRegistry
from .evaluator import Evaluator, make_env_factory

DEFAULT_DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "agent_eval", "datasets", "data")
# Git root (D:\dev\eval): the generated eval_*.json outputs must land here, NOT
# inside the package dir, so they stay out of `git add agent_eval/`.
GIT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
# All evaluation artifacts land in <GIT_ROOT>/results/ by default (timestamped,
# never overwritten). Use --output to override.
RESULTS_DIR = os.path.join(GIT_ROOT, "results")


def _default_out(name_stem: str) -> str:
    """Default output path under results/, timestamped to avoid overwriting."""
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(RESULTS_DIR, f"{name_stem}_{ts}.json")


def _wilson_ci(p: float, n: int, z: float = 1.96) -> List[float]:
    """Wilson score 95% confidence interval; n=0 -> [0,0]."""
    if n == 0:
        return [0.0, 0.0]
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return [round(max(0.0, centre - margin), 4), round(min(1.0, centre + margin), 4)]


def build_registry(datasets: List[str], data_dir: str = DEFAULT_DATA) -> DatasetRegistry:
    """Merge file-isolated dataset dirs into ONE pool."""
    dirs = [os.path.join(data_dir, d) for d in datasets]
    return DatasetRegistry.from_dirs(*dirs)


def run_eval(agent: str = "mock", strategy: str = "reference", datasets: Optional[List[str]] = None,
             k: int = 2, seed_base: int = 0, output: Optional[str] = None,
             tids: Optional[List[str]] = None, mode: str = "plan",
             max_consecutive_failures: int = 3, failure_cooldown_s: float = 10.0) -> dict:
    """Run the unified evaluation and write the report. Returns the summary dict.

    `tids` optionally narrows the agent's default scope (per-agent backend filter).
    `mode` applies to agent=pi: plan (deterministic reference_plan) | llm (real model).
    """
    datasets = datasets or ["biz", "coding"]
    reg = build_registry(datasets)

    if agent == "mock":
        a = UnifiedMockAgent()
        scope = [t.id for t in reg.list_templates()]          # mock runs every domain
        default_out = _default_out("eval_mock_" + "_".join(datasets))
    elif agent == "llm":
        from .llm_agent import LLMToolAgent
        a = LLMToolAgent()
        # Real-LLM tool surface = the memory backend's 6 tools -> only memory-backed
        # templates flow through it (mirror of the pi branch filtering disk-only).
        scope = [t.id for t in reg.list_templates()
                 if (t.env or {}).get("backend", "memory") == "memory"]
        default_out = _default_out("eval_llm_" + "_".join(datasets))
    elif agent == "pi":
        from .pi_adapter import PiAgentAdapter
        a = PiAgentAdapter(strategy=strategy, mode=mode)
        # pi is a coding agent -> only disk-backed templates flow through it
        scope = [t.id for t in reg.list_templates() if t.env.get("backend") == "disk"]
        default_out = _default_out("eval_pi_" + mode + "_" + "_".join(datasets))
    elif agent == "opencode":
        from .opencode_adapter import OpenCodeAgentAdapter
        a = OpenCodeAgentAdapter()
        scope = [t.id for t in reg.list_templates() if t.env.get("backend") == "disk"]
        default_out = _default_out("eval_opencode_" + "_".join(datasets))
    elif agent == "deepseek":
        from .deepseek_adapter import DeepSeekHarnessAdapter
        a = DeepSeekHarnessAdapter()
        scope = [t.id for t in reg.list_templates() if t.env.get("backend") == "disk"]
        default_out = _default_out("eval_deepseek_" + "_".join(datasets))
    else:
        raise ValueError(f"unknown agent: {agent!r} (use 'mock', 'llm', 'pi', 'opencode' or 'deepseek')")

    if tids:
        scope = [t for t in scope if t in set(tids)]
    print(f"统一数据池: {len(reg.list_templates())} 模板 | agent={a.name} | "
          f"跑 {len(scope)} 条 | k={k}")
    ev = Evaluator(reg, a, k=k, seed_base=seed_base, env_factory=make_env_factory(),
                   max_consecutive_failures=max_consecutive_failures,
                   failure_cooldown_s=failure_cooldown_s)
    summary = ev.evaluate(tids=tids)

    if summary.get("aborted"):
        import sys
        print(f"\n⚠️ 评估被熔断中止：{summary['aborted']}", file=sys.stderr)

    o = summary["overall"]
    n = len(scope) * k
    summary["wilson95_ci_pass_k"] = _wilson_ci(o["pass_k"], n)
    # Unified provenance block: every output file carries the same _meta shape so
    # numbers from different runs can never be mixed up silently.
    summary["_meta"] = {
        "agent": a.name,
        "agent_type": "pi-llm" if (agent == "pi" and mode == "llm") else agent,  # mock | llm | pi | pi-llm
        "strategy": strategy if agent == "pi" else None,
        "model": getattr(a, "model", None) or (a.llm_model if agent == "pi" and mode == "llm" else None),
        "judge": "dummy-verifier",               # verifier is the sole pass/fail authority
        "verifier": "deterministic-env-state",
        "tool_surface": getattr(a, "tool_surface", "unknown"),  # slim | full（工具面裁剪口径）
        "dataset_scope": datasets,               # which file-isolated dirs were merged
        "templates_run": len(scope),             # after per-agent backend filter + --tids
        "k": k,
        "seed_base": seed_base,
        "sample_size": n,
    }
    print(f"\n=== {a.name} (统一 Evaluator) ===")
    print(f"  Pass@k={o['pass_at_k']:.2f}  Pass^k={o['pass_k']:.2f}  "
          f"Pass^k(strict)={o['pass_consecutive_k']:.2f}  "
          f"Wilson95%CI={summary['wilson95_ci_pass_k']}  首错用例={o['first_error_cases']}")
    print("  分任务:")
    for tid, info in summary["templates"].items():
        print(f"    {tid:24s} Pass@k={info['pass_at_k']:.2f} "
              f"Pass^k={info['pass_k']:.2f} first_err={info['first_error_steps']}")

    out_path = output or default_out
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print("\nwritten:", os.path.abspath(out_path))
    return summary


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m agent_eval",
        description="Unified agent evaluation: one pool, one Env interface, one report.",
    )
    p.add_argument("--agent", choices=["mock", "llm", "pi", "opencode", "deepseek"], default="mock",
                   help="agent under test (mock=in-process, llm=real LLM tool-calling, "
                        "pi=real pi via TS bridge, opencode=real opencode CLI, "
                        "deepseek=real deepseek-harness headless)")
    p.add_argument("--strategy", choices=["reference", "buggy"], default="reference",
                   help="pi plan strategy (reference=correct, buggy=perturbed); plan mode only")
    p.add_argument("--mode", choices=["plan", "llm"], default="plan",
                   help="pi model decision mode: plan=deterministic reference_plan, "
                        "llm=real LLM via LLM_EVAL_BASE_URL/LLM_EVAL_MODEL")
    p.add_argument("--datasets", default="biz,coding",
                   help="comma-separated file-isolated dataset dirs under datasets/data/")
    p.add_argument("--k", type=int, default=2, help="independent samples per template")
    p.add_argument("--seed-base", type=int, default=0, help="seed base for sampling")
    p.add_argument("--tids", default=None,
                   help="comma-separated template ids to run (default: all in scope)")
    p.add_argument("--output", default=None, help="report output path (default: project root)")
    p.add_argument("--max-consecutive-failures", type=int, default=3,
                   help="连续相同执行错误达此数则判疑似环境问题、熔断中止（0=不熔断）")
    p.add_argument("--failure-cooldown-s", type=float, default=10.0,
                   help="单样本崩溃后等待秒数再继续（让本地慢端点恢复；0=不等待）")
    args = p.parse_args(argv)

    run_eval(agent=args.agent, strategy=args.strategy, mode=args.mode,
             datasets=[d.strip() for d in args.datasets.split(",") if d.strip()],
             k=args.k, seed_base=args.seed_base, output=args.output,
             tids=[x.strip() for x in args.tids.split(",") if x.strip()] if args.tids else None,
             max_consecutive_failures=args.max_consecutive_failures,
             failure_cooldown_s=args.failure_cooldown_s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
