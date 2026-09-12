# context_capture —— 三套 Harness 真实输入 Context 捕获

> 观测 **PI / OpenCode / DeepSeek(dsh)** 三套 agent harness 在真实执行数据集任务时，
> **实际喂给 LLM 的输入 context 究竟是什么**（system + messages + tools，以及它随多轮对话的演化）。
>
> 结论先行：用「统一 LLM 反向代理」在真实执行中捕获（而非脚本模拟）——模拟会重建 context 拼装逻辑，而那正是要测量的对象，会失真。

## 为什么是代理、不是模拟

三套 harness 最终都向同一个 OpenAI 兼容端点发请求，context 的**唯一真值**就是该请求的 body：

| Harness | 调用位置 | context 来源 |
|---|---|---|
| **PI** (llm 模式) | `bridge/pi_bridge.ts` `llmStream()` → `POST /v1/chat/completions` | `context.systemPrompt` + `context.messages` + `context.tools` |
| **OpenCode** | provider `eval-local` (`@ai-sdk/openai-compatible`) | 同上端点 |
| **DeepSeek (dsh)** | `DEEPSEEK_BASE_URL` | 同上端点 |

原生日志（OpenCode JSONL、dsh sessions、`PI` bridge）都不完整、不含输入 context；代理是统一、完整、逐字捕获三者输入 context 的唯一机制，且能直接暴露序列化差异（如 PI 的 `toOpenAIMessages` 丢非文本 part、opencode 内联文件内容）。

## 架构

```
                          ┌─────────────────────────────┐
  PI ───────┐             │   capture_proxy (8899)       │
  OpenCode ─┼─ base_url ─▶│   逐请求落盘 request body     │──▶ 8.134.63.180:7010
  dsh ──────┘  (带前缀)   │   (system+messages+tools)    │    (真实 LLM)
                          └─────────────────────────────┘
```

- 三套 harness 的 `LLM_EVAL_BASE_URL` 全部指向 `http://127.0.0.1:8899/<prefix>/<task_id>`。
- 代理剥离 `<prefix>`，把 `/<prefix>/v1/chat/completions` 重写回上游 `/v1/chat/completions`，并以 prefix 段作为 harness/task 标签。
- 对 harness 透明：三套都会在 base_url 后**自行补 `/v1`**，故 prefix 放在 `/v1` 之前即可，**零改 harness 代码**。

| Harness | 前缀 | base_url 设置 |
|---|---|---|
| PI | `/pi` | `LLM_EVAL_BASE_URL=http://127.0.0.1:8899/pi/<task_id>` |
| OpenCode | `/oc` | `LLM_EVAL_BASE_URL=http://127.0.0.1:8899/oc/<task_id>` |
| DeepSeek | `/dsh` | `LLM_EVAL_BASE_URL=http://127.0.0.1:8899/dsh/<task_id>` |

## 快速开始

```bash
# 一键捕获三套 harness（严格串行）在单个任务上的真实 context
bash context_capture/run_single_task.sh fs_write_001
```

脚本会：① 启动 `scripts/capture_proxy.py` 监听 `127.0.0.1:8899`；② 先后指向代理跑 PI → OpenCode → DeepSeek；③ 逐请求落盘到 `run1/<harness>/<task>/`；④ 跑完自停代理。

> [!IMPORTANT]
> 真实端点 `8.134.63.180:7010` 须**串行**调用（性能有限）；评估本身已串行，代理只做透传 + 落盘，不引入并发。

### 手动运行

```bash
# 后台启动代理
python scripts/capture_proxy.py
# 可选环境变量：CAPTURE_UPSTREAM / CAPTURE_PORT / CAPTURE_OUT / CAPTURE_RESP_MAX

# 分别跑（每个 harness 指向代理）
LLM_EVAL_BASE_URL=http://127.0.0.1:8899/pi/fs_write_001  python -m agent_eval --agent pi --mode llm --datasets coding --k 1
LLM_EVAL_BASE_URL=http://127.0.0.1:8899/oc/fs_write_001  python -m agent_eval --agent opencode --datasets coding --k 1
LLM_EVAL_BASE_URL=http://127.0.0.1:8899/dsh/fs_write_001 python -m agent_eval --agent deepseek --datasets coding --k 1
```

## 捕获内容

对 agent 循环中的**每一次** LLM 调用都落盘一条完整记录：

```json
{
  "harness": "pi", "task": "fs_write_001", "turn_seq": 7, "timestamp": "...",
  "request":  { "model": "...", "messages": [...], "tools": [...],
                "temperature": 0, "max_tokens": 2048, "stream": false },
  "response": { "choices": [ { "message": { "content": "...", "tool_calls": [...] } } ] },
  "request_chars": 12345, "request_tokens_est": 3086
}
```

- `messages` 含完整多轮历史，随 tool result 累积膨胀——对比三套 context 工程差异的核心数据。
- `tools` 是该 harness 实际下发的工具 schema（opencode 经 `opencode_slim.ts` 裁剪过；PI 真实工具面 = bash/edit/find/grep/ls/read/write）。
- 同时落 `response`，便于把"输入 context"与"LLM 返回"对上。

## 分析与对比报告

| 文件 | 作用 |
|---|---|
| `run_single_task.sh` | 一键捕获封装（PI→OC→dsh 串行） |
| `run1/gen_report.py` | 生成 `run1/context_comparison_report.md`（三套 `fs_write_001` 输入的逐字段对比） |
| `gen_oc_vs_dsh_full.py` | 生成 `oc_vs_dsh_full_comparison.md`（OpenCode vs DeepSeek 完整版逐字段对比） |

> [!NOTE]
> 关键观测线索（详见报告）：
> - **n_ctx 截断证据**：本地端点 `n_ctx=4096`。OpenCode 初始 prompt ~6906 token 超出上限，代理里可直接看到截断/裁剪是否生效——这正是"工具面裁剪是技术妥协非语义限定"的实证。
> - **工具面差异**：PI(7个)/opencode(slim 后)/dsh(25个) 各自下发的工具集合、参数命名（path/filePath/file_path 三套三样）、DSH 独有的 `sandbox_permissions`+`justification` 治理字段。
> - **序列化差异**：只有抓 wire 格式才能诚实对比（PI 丢非文本 part、opencode 内联文件、dsh 多一条 runtime-context user 消息）。

## 与评估口径的关系

本捕获**不改评估结论**：verifier 仍只看最终环境状态 + 过程硬约束（confirm/clarify）。捕获是独立的观测旁路，与 `eval_*_llm.json` 互不干扰，可作"三 harness context 工程对比"报告的实证源。
