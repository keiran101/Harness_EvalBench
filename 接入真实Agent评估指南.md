# 接入真实 Agent 并完成评估：方法与实操

> 面向：把真实 LLM Agent（以 pi-main 为例）接入 `agent_eval` 框架并跑出可信评估结果的完整路径。
> 配套框架：`D:\dev\eval\agent_eval`（Python，零依赖，39 测试绿）。

---

## 0. 一图总览：框架与真实 Agent 的三个接触面

```
   agent_eval (Python)                         真实 Agent (任意形态)
 ┌──────────────────────────┐                ┌──────────────────────────┐
 │ DatasetRegistry          │                │ pi coding-agent (TS/Bun) │
 │  base/Middle/hard 模板   │                │  Agent(prompt/steer/      │
 │  verifier(双检+硬否决)   │                │   followUp, tools, 状态)  │
 │  metrics(Pass@k/Pass^k)  │   接触面①     │                          │
 │  judge(Dummy/LLM)        │ ─────────────► │  接触面②  (进程桥)        │
 │  evaluator(编排+k 采样)   │                │  接触面③  (streamFn 注入) │
 │  closure(坏例回流)       │                │                          │
 └──────────────────────────┘                └──────────────────────────┘
        ▲ 报告(JSON+表格)                           ▲ 真实轨迹/真实工具
```

评估的本质（第六章）：**评估对象 = 模型 + Harness 组合体**。接入真实 agent 时，我们把「Agent 的决策循环」接进「框架的评测单元」，框架负责：给任务（instance）→ 提供环境（env）→ 收轨迹（trajectory）→ 验证最终状态（verifier）→ 聚合指标（metrics）。

---

## 1. 三个接触面：按 agent 形态选

| 接触面 | 适用形态 | 做法 | 代价 |
|---|---|---|---|
| **① 同进程适配** | agent 是 Python 库/可内嵌 | 实现 `run(instance, env) -> Trajectory`，直接 import 调用 | 最小；要求 agent 与框架同语言 |
| **② 进程桥** | agent 是外部 CLI / 服务 / 其他语言 | `subprocess` 起 agent 进程，环境=真实 fs/HTTP，verifier 查最终状态 | 中等；需定义进程级协议（输入 prompt / 输出状态） |
| **③ LLM 层注入（streamFn）** | agent 的 LLM 调用层可插拔（如 pi 的 `AgentOptions.streamFn`） | 注入 deterministic/mock streamFn 驱动 agent 完整 loop（工具调用、状态管理都真实执行） | 低到中；**无 API key 也能跑**，成本为零 |

pi（Bun/TS 编码 agent）同时适用 ② 和 ③：
- **② 进程桥**：`pi -p "<任务指令>"` 在临时 workspace 里真实操作文件 → Python 端查 fs 最终状态。
- **③ streamFn 注入**（更优）：pi 的 `Agent` 构造参数 `streamFn` 可注入（已核实 `agent-session.ts:3131` 从 `agent.streamFunction` 取），写一个确定性 streamFn 即可**零成本驱动它的完整 agent loop**，工具（bash/fs/git）仍真实执行——这正好满足第六章「评估要覆盖 Harness 决策层」的要求，且不烧 token。

---

## 2. 标准接入流程（以 ① 同进程为例，②③ 同构）

### Step 1：实现 Agent 适配器（唯一必须写的代码）

```python
# agent_eval/agent_eval/pi_adapter.py
from agent_eval.core import Step, Trajectory
from agent_eval.datasets.templates import TaskInstance
from agent_eval.environments.tool_env import ToolCallingEnv

class PiAgentAdapter:
    """把 pi（真实编码 agent）包装成框架的 run(instance, env) -> Trajectory。"""
    def __init__(self, name="pi", provider="anthropic", model="claude-sonnet-4"):
        self.name = name
        # ① 同进程：构造 pi Agent（注入 streamFn / apiKey）
        # ③ streamFn：self.agent = Agent({streamFn: mock_stream_fn, ...})

    def run(self, instance: TaskInstance, env: ToolCallingEnv) -> Trajectory:
        traj = Trajectory()
        # 1) 把 instance 翻译成 agent 能做的任务（instruction + 环境说明）
        prompt = build_prompt(instance)   # instruction + 工具清单 + 初始状态
        # 2) 调用 agent（pi: await agent.prompt(prompt)）
        #    —— 每个工具调用映射为一个 Step，is_error 标记不可接受动作
        #    —— 最终回答放入 traj.answer
        # 3) 返回轨迹
        return traj
```

**要点**：
- **轨迹要忠实**：agent 的每一步工具调用都记成 `Step(action, observation, state_before, state_after, is_error, error_category)`——这是「首个错误步归因」成立的前提。
- **环境对齐**：`env` 的最终状态必须能被 verifier 检查。进程桥时，env 就是真实 fs/HTTP，verifier 直接查 fs。
- **错误标注**：工具失败、危险动作未确认、死循环都标 `is_error=True` + 分类，让归因和硬否决（must_not_do）生效。

### Step 2：数据集适配（关键决策）

真实 agent 的工具面 ≠ 我们 base 数据集的虚拟工具面（联系人/订单/计数器）。**要么**：
- **A. 给 agent 设计匹配的 domain**：pi 是编码 agent → 新建 `domain=coding` 数据集（改文件、读配置、跑脚本、git 操作），verifier 检查真实 fs 状态——推荐，评估才有意义；
- **B. 用 agent 自带评估**：pi 自带 `packages/evals`（vitest-evals harness），可直接复用其 harness 收集轨迹，但断言是 QA 式文本（`expect(output).toBe("Paris")`），缺状态验证/双检/防泄漏——可对照我们的体系补强。

数据集文件用现有 JSON 机制：`agent_eval/datasets/data/coding/*.json`，`DatasetRegistry.from_dir` 加载，自动 `wire_leak_guard`。

### Step 3：评分器选择

| 场景 | 选择 |
|---|---|
| 成功条件可机械化检查（状态/文件/退出码） | `DummyJudge`（确定性，零成本）——**首选** |
| 结果需要主观/语义判断（回答质量、方案合理性） | `LLMJudge`：`pip install openai` + key，rubric 分维 + 锚定 + 偏差校正 |

```python
ev = Evaluator(reg, pi_agent, k=4, seed_base=0,
               judge=LLMJudge(api_key=..., rubric={...}))
```

### Step 4：跑评估 + 读报告

```bash
python examples/run_pi_eval.py        # 输出 eval_output.json + 表格
```

报告含：Pass@k（能力上限）/ Pass^k（业务可靠性）/ Pass^k(strict) / first_error 归因 / 分模板明细 / by-capability 切片。

---

## 3. pi-main 接入本框架的落地差异（实证）

已核实的事实（源码级）：
- pi 是 **Bun/TypeScript monorepo**（agent-core / coding-agent / ai / evals / telemetry / tui），本机**无 bun、无 LLM key**、依赖未安装。
- `packages/evals` 自带 harness：`createPiCodingAgentHarness()` → `run({input, signal, setArtifact})` → `{output, events(含 tool_call/tool_result), usage(tokens/cost), timings}`——**与我们的 Evaluator 抽象同构**（instance→run→report），轨迹事件可直接映射为我们的 `Trajectory.steps`。
- `Agent`（agent-core）支持注入 `streamFn` / `getApiKey` / `beforeToolCall` / `afterToolCall` / `shouldStopAfterTurn`——**无 key 评估可行**（确定性 streamFn 驱动 loop，工具真实执行）。
- 自带 eval 断言是 **QA 式文本**（`smoke.eval.ts`：`expect(result.output.trim()).toBe("Paris")`），**未覆盖**：状态验证、FAIL_TO_PASS/PASS_TO_PASS 双检、防泄漏、Pass@k/Pass^k 分层、失败归因——这是它的评估体系与我们框架的主要差距，也是接入后我们能补的价值。

---

## 4. 当前环境下的执行结论

| 路径 | 可行性 | 前置条件 |
|---|---|---|
| ① 同进程（Python 内嵌） | 不适用 | pi 是 TS，非同语言 |
| ② 进程桥 + coding 数据集 | ✅ 可行 | 需 bun（或 node 兼容）+ npm install + **LLM key** |
| ③ streamFn 注入 + coding 数据集 | ✅ **最推荐** | 需 bun + npm install；**无需 key**（mock streamFn） |
| 跑 pi 自带 evals 单元测试 | ✅ 可立即做 | npm install 完成即可（vitest 非 LLM 部分） |

**结论**：完整接入需等依赖装好（进行中）；无 key 时走 ③ 即可完成「评估 pi 的 Harness 决策层」的闭环演示；要评估真实智能水平则需配 key。
