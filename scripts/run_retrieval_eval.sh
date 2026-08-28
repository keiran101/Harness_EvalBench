#!/usr/bin/env bash
# =============================================================================
# 检索域三 Agent 真实 LLM 评估 —— 串行顺序脚本（无进度条）
# 顺序：deepseek -> pi -> opencode（严格串行，绝不对本地 LLM 端点并发）
#
# 用法：
#   bash scripts/run_retrieval_eval.sh
#
# 产物：每个 agent 跑完自动落 D:\dev\eval\results\eval_<agent>_retrieval_keycases_<时间戳>.json
#       cli.py 默认落 results/ 且带时间戳，无需手动指定 --output
# =============================================================================

set -e   # 任一 agent 非零退出即中止，避免带着失败继续跑下一个

# ---- 本地 LLM 端点（串行硬约束：必须串行调用，严禁并发压测）----
export LLM_EVAL_BASE_URL="http://8.134.63.180:7010"
export LLM_EVAL_MODEL="google/gemma-4-12b-qat"

# 进入包目录（cli 入口在 agent_eval/agent_eval/cli.py，模块路径需在此）
cd "$(dirname "$0")/../agent_eval" || exit 1

# ---- 评估参数 ----
K=5                                   # 每模板独立样本数（k=5：更稳的 Wilson CI + 更可信的一致性指标）

# 运行单个 agent（stdout/stderr 直出终端，无进度条）
run_agent () {
  local agent="$1" mode="$2" label="$3" idx="$4" total_agents="$5"
  echo
  echo "[$(date +%H:%M:%S)] >>> $idx/$total_agents $label 启动 (k=$K)"
  python -m agent_eval --agent "$agent" ${mode:+--mode "$mode"} \
        --datasets retrieval,keycases --k "$K"
  echo "[$(date +%H:%M:%S)] <<< $label 完成"
}

echo "=================================================="
echo "[$(date +%H:%M:%S)] 开始检索域串行评估 (deepseek -> pi -> opencode, k=$K)"
echo "  三 agent 串行约 4 小时（本地慢端点，严禁并发）"
echo "=================================================="

# 1) deepseek（DSH_SLIM 默认开，需满血加 DSH_SLIM=0 前缀）
run_agent deepseek ""    "1/3 deepseek" 1 3

# 2) pi（--mode llm 真实 LLM 决策；pi 固定满血工具面）
run_agent pi       "llm" "2/3 pi"       2 3

# 3) opencode（最重，每次起 bun 跑真实 CLI；OPENCODE_SLIM 默认开）
run_agent opencode ""    "3/3 opencode" 3 3

echo "=================================================="
echo "[$(date +%H:%M:%S)] 全部完成。产物位于 results/（带时间戳）"
echo "=================================================="
