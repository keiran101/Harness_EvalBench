#!/usr/bin/env bash
# =============================================================================
# 检索域三 Agent 真实 LLM 评估 —— 串行顺序脚本
# 顺序：deepseek -> pi -> opencode（严格串行，绝不对本地 LLM 端点并发）
#
# 用法：
#   bash scripts/run_retrieval_eval.sh
#
# 产物：每个 agent 跑完自动落 D:\dev\eval\results\eval_<agent>_retrieval_<时间戳>.json
#       （cli.py 已改为默认落 results/ 且带时间戳，无需手动指定 --output）
# =============================================================================

set -e   # 任一 agent 非零退出即中止，避免带着失败继续跑下一个

# ---- 本地 LLM 端点（串行硬约束：必须串行调用，严禁并发压测）----
export LLM_EVAL_BASE_URL="http://8.134.63.180:7010"
export LLM_EVAL_MODEL="google/gemma-4-12b-qat"

# 进入包目录（cli 入口在 agent_eval/agent_eval/cli.py，模块路径需在此）
cd "$(dirname "$0")/../agent_eval" || exit 1

echo "=================================================="
echo "[$(date +%H:%M:%S)] 开始检索域串行评估 (deepseek -> pi -> opencode)"
echo "=================================================="

# 1) deepseek（约 40s/次 × k2 × 30 模板 ≈ 40min）
echo "[$(date +%H:%M:%S)] >>> 1/3 deepseek 启动"
python -m agent_eval --agent deepseek --datasets retrieval --k 2
echo "[$(date +%H:%M:%S)] <<< deepseek 完成"

# 2) pi（--mode llm 真实 LLM 决策，约 19s+/次 × 60 ≈ 20min）
echo "[$(date +%H:%M:%S)] >>> 2/3 pi 启动"
python -m agent_eval --agent pi --mode llm --datasets retrieval --k 2
echo "[$(date +%H:%M:%S)] <<< pi 完成"

# 3) opencode（最重，每次起 bun 跑真实 CLI，约 57s/次 × 60 ≈ 57min）
echo "[$(date +%H:%M:%S)] >>> 3/3 opencode 启动"
python -m agent_eval --agent opencode --datasets retrieval --k 2
echo "[$(date +%H:%M:%S)] <<< opencode 完成"

echo "=================================================="
echo "[$(date +%H:%M:%S)] 全部完成。产物位于 results/（带时间戳）"
echo "=================================================="
