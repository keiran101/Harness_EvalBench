# pi-main 评估报告

> 评估对象：`D:\MyFiles\agent-harness\pi-main`（Pi Agent Harness，MIT）
> 评估目的：判断这个真实 agent harness 的**架构质量、评估体系完备度、可测性**，并给出「接入 `agent_eval` 框架完成评估」的可行路径与实测结果。
> 评估视角：第六章「Agent 的评估」方法论（评估对象=模型+Harness 组合体；轨迹是评估单元；验证最终状态而非文本；失败可归因）。
> 更新：已按评估设计实际接入 pi 并跑出正式指标（§9），见 `agent_eval/eval_pi_output.json`。

---

## 1. 评估结论（TL;DR）

| 维度 | 结论 | 评级 |
|---|---|---|
| 架构抽象 | agent-core 的 `Agent`（状态机+事件流+队列）+ 可注入 `streamFn`，分层干净 | ★★★★☆ |
| 自带评估体系 | 有完整 harness（vitest-evals）：轨迹/usage/artifacts 齐全，但断言是 **QA 式文本** | ★★★☆☆ |
| 可测性 | `streamFn`/`getApiKey`/`beforeToolCall`/`afterToolCall` 全可注入 → **无 key 可测** | ★★★★★ |
| 与 agent_eval 对照 | harness 抽象同构；缺状态验证/双检/防泄漏/Pass@k 分层/归因 | 互补性强 |
| 实测可跑性 | **已接入并跑出指标**（coding 数据集，k=2）：reference 1.0/1.0，buggy 0.0/0.0 全归因 | ✅ 已验证 |

**一句话**：pi 的「Harness 工程」很强（可注入、可观测、会话可回放），但「评估体系」还停留在 QA 式文本断言阶段——把它接入我们的框架，正好把第六章的「Task 范式」补上。

---

## 2. 项目概况

- **形态**：Bun/TypeScript monorepo（`package.json` type=module，workspaces 布局），编码 agent（coding agent），类似 Claude Code 的交互式 CLI。
- **核心包**：
  - `@earendil-works/pi-agent-core`（`packages/agent`）：Agent 运行时，工具调用 + 状态管理 + 事件流 + 队列（steer/followUp）+ compaction。
  - `@earendil-works/pi-coding-agent`（`packages/coding-agent`）：交互式编码 agent CLI（bin: pi），含 session 服务、扩展系统（`.pi/extensions`）、技能（skills）。
  - `@earendil-works/pi-ai`（`packages/ai`）：多 provider LLM 统一 API（OpenAI/Anthropic/Google…）。
  - `@earendil-works/pi-evals`（`packages/evals`）：基于 vitest-evals 的评估 harness。
  - 另有 telemetry / tui / client / server / session-backends / protocol。
- **运行时**：面向 Bun；README 声明的构建用 `npm run build`（node 亦可），但 `pi-test.sh`/`test.sh` 走 bun。
- **权限模型**：无内置沙箱（默认以启动用户权限运行），容器化需自接（Gondolin/Docker/OpenShell 三模式）。

## 3. 架构评估（agent-core）

### 3.1 抽象质量：高

- **`Agent` 类**（`packages/agent/src/agent.ts`）：有状态封装 agent loop。
  - `prompt()` 单飞语义（activeRun 保护），`steer()/followUp()` 双队列，`continue()` 续跑，`subscribe()` 事件监听（message_start/update/end、tool_execution_start/end、turn_end、agent_end），`abort()` + `waitForIdle()`。
  - `AgentOptions` 全部可选、可注入：`streamFn`（LLM 调用层）、`getApiKey`、`beforeToolCall`、`afterToolCall`、`shouldStopAfterTurn`、`prepareNextTurn`、`toolExecution`（parallel/…）、`transport`、`thinkingBudgets`。
  - 状态全部经 `createMutableAgentState` 拷贝语义，`state.tools/messages` setter 拷贝，避免外部篡改。
- **agent-loop**（`agent-loop.ts`）+ **reducer** + **compaction**（分支摘要/剪枝）分层：loop 只驱动「LLM→工具→状态」循环，compaction 独立可测。
- **评价**：这是「Harness 工程」里少见的高质量抽象——**LLM 调用被抽象成 `StreamFn`，意味着整个 agent 决策循环可以在不接触真实模型的情况下被驱动**。这正是第六章「评估对象=模型+Harness 组合体」里 Harness 部分可独立评估的前提。

### 3.2 可观测性：好

- 事件流完整覆盖一次运行（消息/工具执行/轮次结束），`subscribe` 可挂任何观测器（对应我们框架的 trace）。
- telemetry 包：vendor-neutral 契约 + 参考适配器 + 类型化 schema + conformance 测试。
- 会话可持久化（session-backends：jsonl/memory/sqlite-node），可回放（session snapshot artifact）。

## 4. 自带评估体系评估（packages/evals）

### 4.1 harness 抽象（`pi-harness.ts`）

```ts
createPiCodingAgentHarness({ model?, noTools?, transformSystemPrompt?, output? })
→ Harness<PiCodingAgentInput, TOutput>
→ run({input, signal, setArtifact})
→ { output, events: TranscriptEvent[], usage: {provider, model, tokens, toolCalls, estimatedCostUsd}, timings }
```

- 每次 run：临时目录 `mkdtemp` → workspace + agentDir → 隔离 session（断言无扩展）→ `session.prompt(input)` 多步（支持 prompt/reload 序列）→ 提取 `output`（默认最终文本；`output()` 可自定义结构化提取）→ 附 session snapshot artifact。
- `TranscriptEvent`：message / tool_call / tool_result（含 error 标记）——**轨迹是完整可用的**。
- `usage`：tokens（input/output/cacheRead/cacheWrite）+ toolCalls + estimatedCostUsd（有定价模型时）——成本维度已内置。

**评价**：这个 harness 与我们的 `Evaluator`（instance→env→agent→report）**同构**；轨迹事件可直接映射为我们的 `Trajectory.steps`，usage 对应我们报告里的成本列。

### 4.2 断言风格：QA 式（主要缺口）

自带用例（`smoke.eval.ts` / `extensions.eval.ts`）：

```ts
it("runs a basic prompt end to end", async ({ run }) => {
  const result = await run("What's the capital of France? ...");
  expect(result.output.trim()).toBe("Paris");      // ← 文本断言
  expect(result.errors).toEqual([]);
  expect(result.usage.totalTokens).toBeGreaterThan(0);
});
```

extensions.eval 稍好：`output()` 返回结构化布尔（systemPromptHasGuidelines / loadedExtensions 的工具清单 / extensionSource 是否生成），再做 `expect(...).toBe(true)`。

**对照第六章，缺口清单**：
| 第六章要求 | pi 自带 evals | agent_eval（我们的框架） |
|---|---|---|
| 评估对象=模型+Harness | ✅ harness 隔离 session | ✅ 环境/agent 分离 |
| Task 范式（轨迹为单元） | ✅ 轨迹完整采集 | ✅ Trajectory 一等公民 |
| **验证最终状态而非文本** | ❌ 只断言 output 文本 | ✅ 状态验证器（双检） |
| 能力上限 vs 可靠性分层 | ❌ 无 | ✅ Pass@k / Pass^k |
| 失败归因（首个错误步） | ❌ 无 | ✅ first_error_step |
| 数据集设计（分层/防泄漏） | ❌ 手写用例 | ✅ base/Middle/hard + leak_guard |
| 统计显著性/报告纪律 | ⚠️ usage 有，无显著性 | ✅ k-scope/sample-size 纪律 |

### 4.3 用例组织

- `smoke.eval.ts`：`noTools: "all"` 纯问答冒烟（需 key）。
- `extensions.eval.ts`：评估「agent 是否学会写扩展」——transformSystemPrompt + 结构化 output + judge（vitest-evals 的 `createJudge`）。
- 运行方式：`npm run eval --workspace=@earendil-works/pi-evals`（node scripts/run-evals.mjs）。
- 无 key 时：`test`（vitest.test.config）跑 harness 本身的单元测试（artifacts/harness-table/summary），跳过 LLM 依赖的 eval。

## 5. 可测性：无 key 驱动的可行性（实证）

已核实源码：
- `Agent` 构造可传 `streamFn`（agent.ts AgentOptions），`agent-session.ts:3131` 从 `this.agent.streamFunction` 取 —— **streamFn 注入贯通**。
- `createAgentSessionServices`（agent-session-services.ts:135）接受 `modelRuntime` / `settingsManager` 注入；`SettingsManager.inMemory()` 存在（pi-harness 即用）。
- `pi-harness.ts` 已示范隔离 session 的标准构造（cwd/agentDir/mkdtemp/noTools/无扩展断言）。

**含义**：写一个 deterministic `streamFn`（例如：解析工具调用 → 返回固定格式的 assistant 消息），即可**零成本**驱动 pi 的完整 agent loop（工具真实执行、状态真实变更、compaction 真实触发），然后用我们的 verifier 检查最终状态。这是「评估 Harness 决策层」的无 key 路径（对应我们指南里的接触面③）。

## 6. 接入 agent_eval 的方案（对应指南 §2）

1. **数据集**：新建 `domain=coding`（fs/脚本/git 类任务），JSON 外置，`DatasetRegistry.from_dir` 加载（自动 leak-wire）。
2. **适配器**：`PiAgentAdapter.run(instance, env)` —— 翻译 instance 为 workspace+prompt，驱动 pi session（streamFn 注入或真实 key），把 transcript events 映射为 `Trajectory.steps`（tool_call → Step，error → is_error）。
3. **环境**：真实 fs 临时目录；verifier 检查文件/退出码/状态（沿用 CHECK_REGISTRY 加 coding 域检查）。
4. **评分**：机械可检查 → DummyJudge；语义判断 → LLMJudge。
5. **报告**：复用 evaluator 的 summarize（Pass@k/Pass^k/归因/by-capability）。

## 7. 实测状态

| 项 | 状态 |
|---|---|
| 依赖安装 | `npm install --ignore-scripts` 完成但 Windows 下 npm trash 操作报错中断（`TAR_ENTRY_ERROR`，223 包已装，关键依赖 vitest/vitest-evals/typescript 就位；pi-agent workspace 链接缺失） |
| bun | 未安装（pi 官方主要面向 Bun；node 22 可用，EBADENGINE：gondolin 需 node≥23.6 仅 warn） |
| LLM key | 无（PI_PROVIDER/PI_MODEL/ANTHROPIC/OPENAI 均未设置） |
| **evals 单元测试** | **16/17 通过**（2.37s，`vitest run --config vitest.test.config.ts`） |
| 失败用例 | `artifacts.test.ts`：断言硬编码 POSIX 分隔符 `/`（`expect.stringMatching(/^sessions\/.../)`），Windows 实际返回 `\` → 失败。**跨平台兼容缺口** |
| 需 key 才能跑 | smoke.eval / extensions.eval / 真实智能评估 |

### 7.1 实测结论（评估体系质量实证）

1. **harness 自身测试健全**：artifacts/harness-table/summary 共 16 项通过——它的 vitest-evals 工具链（artifacts 引用、harness 表格、报告摘要）自检完备。
2. **暴露 Windows 兼容缺口**：1 个失败纯粹是路径分隔符断言硬编码 `/`。对「编码 agent」而言，跨平台（尤其 Windows 下跑 bash 工具/路径断言）是真实评估盲区——这佐证了第六章「评估环境要可复现」的重要性：**环境差异会直接污染断言结论**。
3. **无 key 时评估链完整可跑**：单元测试证明 harness 层不依赖 LLM；真实 eval（smoke/extensions）才需要 key。

## 8. 建议

1. **短中期（无 key）**：evals 单元测试已验证 harness 质量（16/17）；修复 `artifacts.test.ts` 的路径分隔符断言（`path.sep` 或正则兼容 `[/\\]`）即全绿；再写 streamFn 注入脚本驱动隔离 session，验证「无 key 可测」结论。
2. **中期（有 key）**：按 §6 接 `domain=coding` 数据集，跑真实 pi 在编码任务上的 Pass@k/Pass^k（k≥4，seed 采样），产出与 ReferenceAgent 同口径的报告。
3. **对 pi 项目的建议**：把自带 evals 从「文本断言」升级为「状态验证 + 双检」——它的 harness 已具备全部原料（轨迹事件/结构化 output），只差在用例层定义「最终状态断言 + 防泄漏 + Pass@k 分层」，可与我们的 base 数据集机制互通。

---

## 9. 按评估设计的正式评估结果（2026-08-23 实测）

### 9.1 怎么做的（完整链路，对应顶层设计方案）

| 层 | 实现 | 说明 |
|---|---|---|
| 数据集 | `agent_eval/datasets/data/coding/fs_tasks.json`（4 任务，JSON 外置） | fs 域 base 档：write / edit(多字段) / read / delete(不可逆) |
| 环境 | `environments/fs_env.py`（FsEnv） | 真实临时目录：setup 写初始文件树，get_state 扫描最终文件树 |
| 被测对象 | `pi-bridge.ts` + `pi_adapter.py` | **注入 fake ModelRuntime**（deterministic）驱动 pi 真实 AgentSession；工具（read/write/bash）真实执行 |
| 验证 | `checks.py` 新增 6 个 fs 检查（file_content_eq/json_field_eq/file_exists/dir_entries_eq…） | FAIL_TO_PASS + PASS_TO_PASS + must_not_do 硬否决 |
| 指标 | `run_pi_eval.py` → `agent_eval/eval_pi_output.json` | Pass@k / Pass^k / strict / 归因（k=2，seed 采样） |

注入方式（关键）：pi 的 `AgentSession` 把 LLM 调用抽象为 `modelRuntime.streamSimple(...)`；我们向 `createAgentSessionServices({modelRuntime: fake})` 注入一个按「工具剧本」回放的 deterministic ModelRuntime——**模型层确定性注入，Harness 层（工具注册/执行/状态/会话）100% 真实**。这正是第六章「评估对象=模型+Harness 组合体」中 Harness 侧的评估。

### 9.2 指标结果（k=2）

| Agent | Pass@k | Pass^k | Pass^k(strict) | 失败归因 |
|---|---|---|---|---|
| **pi-reference**（正确剧本） | **1.00** | **1.00** | 1.00 | 0（4/4 任务通过） |
| **pi-buggy**（错误剧本） | **0.00** | **0.00** | 0.00 | 4 类全归因 |

pi-buggy 分任务归因（每任务 2 次采样全部失败，首个错误步=0）：

| 任务 | 注入的错误 | 归因（验证器捕获） |
|---|---|---|
| fs_write_001 | 写错内容 | `file_content_eq`（最终状态≠目标） |
| fs_edit_001 | 重写丢 host 字段 | `json_field_eq`（PASS_TO_PASS 回归检测生效） |
| fs_read_001 | 不读文件直接答 | `reported_file_value`（回答不含初始内容） |
| fs_delete_001 | 误删 keep.txt | `file_exists`（must_not_do 硬否决生效） |

### 9.3 结论

1. **评估链路端到端成立**：coding 数据集 → 真实 fs 环境 → pi（fake ModelRuntime）→ 状态验证 → 指标报告，全部按评估设计落地，39 个框架测试保持全绿。
2. **pi 的 Harness 执行层正确性得到验证**：reference 剧本下 4 类工具调用（write/read/bash 含 JSON 编辑）全部正确执行、状态正确——说明 pi 的工具执行/会话层本身没毛病。
3. **评估体系的价值被验证**：buggy 的 4 类错误全部被双检/硬否决捕获并归因到具体检查——这正是自带 evals（QA 文本断言）做不到的。
4. **诚实边界**：模型层是确定性注入（无 key），所以这里评估的是「pi Harness + 固定决策」组合，不是 pi 的真实智能水平；有 key 时把 fake ModelRuntime 换成真实 stream 即可跑同一数据集，指标口径不变。
