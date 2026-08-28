#!/usr/bin/env bash
# run_single_task.sh — 单任务捕获 PI / OpenCode / DeepSeek(dsh) 真实 context
#
# 用法: bash context_capture/run_single_task.sh [task_id]
# 默认任务: fs_write_001
#
# 工作机制:
#   1. 启动 capture_proxy (scripts/capture_proxy.py) 监听 127.0.0.1:8899
#   2. 三个 harness 的 LLM_EVAL_BASE_URL 指向代理(带 harness/task 路径前缀)
#   3. 代理逐请求落盘完整 context 到 ./run1/<harness>/<task>/
#   4. 严格串行(本地 LLM 不能并发), 跑完自停代理
# 零改 eval: adapter 默认读 LLM_EVAL_BASE_URL env, 且各自补 /v1。

set -u
ROOT="$(cd "$(dirname "$0")" && pwd)"
PROXY_PY="D:/dev/eval/scripts/capture_proxy.py"
CAP_OUT="$ROOT/run1"
TASK="${1:-fs_write_001}"
PORT=8899
UPSTREAM="8.134.63.180:7010"

export CAPTURE_UPSTREAM="$UPSTREAM"
export CAPTURE_PORT="$PORT"
export CAPTURE_OUT="$CAP_OUT"
export CAPTURE_RESP_MAX="400000"     # 单条响应记录上限(字节)

mkdir -p "$CAP_OUT"
echo "[runner] TASK=$TASK  CAP_OUT=$CAP_OUT  UPSTREAM=$UPSTREAM"

# ---- 启动代理 ----
python "$PROXY_PY" &
PROXY_PID=$!
echo "[runner] proxy started pid=$PROXY_PID"

cleanup() {
  echo "[runner] stopping proxy pid=$PROXY_PID"
  kill "$PROXY_PID" 2>/dev/null || true
}
trap cleanup EXIT

sleep 3   # 等代理监听起来

run_one() {
  local agent="$1"; local prefix="$2"; local extra="$3"
  echo ""
  echo "########## $agent  (base_url prefix=/$prefix) ##########"
  LLM_EVAL_BASE_URL="http://127.0.0.1:$PORT/$prefix/$TASK" \
    python -m agent_eval --agent "$agent" --datasets coding --tids "$TASK" --k 1 $extra
  echo "########## $agent finished (rc=$?) ##########"
}

# 严格串行: PI -> OpenCode -> DeepSeek
run_one pi        pi  "--mode llm"
run_one opencode  oc  ""
run_one deepseek  dsh ""

echo ""
echo "[runner] ===== capture tree ====="
find "$CAP_OUT" -type f | sort
echo "[runner] done."
