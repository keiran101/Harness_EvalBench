# agent_eval —— Agent 评估框架

> 面向 **agent harness** 的评估框架：评估单元是 Task / 轨迹（episode），**验证最终环境状态而非文本对错**（不是 QA）。
> 按《Agent 评估顶层设计方案》实现的 6 层架构，指导来源《AI Agents in Depth》第六章。运行时**零外部依赖**（纯标准库）。

## 快速开始

```bash
cd agent_eval

# 无需任何 API key / 网络：端到端 demo，输出 eval_output.json
python examples/run_demo.py

# 33 个单元/集成测试
python -m pytest tests/ -q
```

demo 输出（k=4，15 个 base 模板）：

| agent | Pass@k（能力上限） | Pass^k（可靠性） | Pass^k(strict) | 失败归因数 |
|---|---|---|---|---|
| reference | 1.00 | 1.00 | 1.00 | 0 |
| flaky | 1.00 | **0.25** | 0.00 | 45 |
| buggy | 0.20 | 0.20 | 0.20 | 48 |

> [!NOTE]
> **核心论点演示**：只看 `Pass@k` 会把一个 flaky 系统误判为可上线。头部分数高 ≠ 业务可靠。

## 6 层架构

| 层 | 模块 | 职责 |
|---|---|---|
| 0 数据模型 | `core.py` | `Step` / `Trajectory`（轨迹=评估单元）/ `VerificationResult` / `EvalReport` |
| 1 数据集 | `datasets/` | 参数化模板 + 能力标签 + `FAIL_TO_PASS`/`PASS_TO_PASS` 双检 + 防泄漏 + Registry |
| 2 指标 | `metrics/` | `Pass@k`（上限）/ `Pass^k`（可靠性）/ strict 连续 k |
| 3 环境 | `environments/` | `ToolCallingEnv`：工具暴露、确定性状态验证、reset、瞬时失败注入 |
| 4 Judge | `judge/` | `DummyJudge`（离线规则）/ `LLMJudge`（rubric+锚定+偏差校正，需 key） |
| 5 可观测性 | `observability/` | 轻量 trace（逐 step span）+ 通过率漂移检测 |
| 6 闭环 | `closure/` | 坏例 → `RegressionStore`，trajectory-prefix 边界集 |
| 编排 | `evaluator.py` | 用例→环境→Agent→验证→Judge→报告，k 次独立采样 |

## 数据集层

- **三档递增**（步骤数/工具数）：`base` 1–2步/1工具、`Middle` 3–5步/2–3工具、`hard` 6+步/多工具+陷阱。
- **base 档 5 类基础能力**（每类 3 模板）：`tool_call` · `state_read` · `error_recovery` · `clarify` · `confirm`。
- **双检 + 硬否决**：`FAIL_TO_PASS`（问题真被解决）+ `PASS_TO_PASS`（没引入回归）全过才判成功；任一 `must_not_do` 红线未过即整体失败（二元奖励）。
- **外置存储**：模板存于 `../data/base/*.json`（每能力一文件，可 diff）；`DatasetRegistry.from_file/from_dir` 加载；`with_base()` 为内置默认集。加载时自动 `wire_leak_guard`（canary/新鲜度/隔离）。
- **检查以 check spec 表达**：`{"fn": <注册名>, "args": {...}}`，逻辑在 `datasets/checks.py` 的 `CHECK_REGISTRY`，故数据集文件可纯数据序列化。

```python
from agent_eval.datasets.registry import DatasetRegistry
reg = DatasetRegistry.from_dir("../data/base")
inst = reg.instantiate("base_tool_call_001", seed=7)   # 参数化实例
result = reg.verify(inst, final_state, trajectory)      # 双检 + 硬否决
```

## 如何接入真实系统

1. **换真实 Agent**：实现 `run(instance, env) -> Trajectory`，轨迹里用 `Step.is_error` 标记不可接受动作。
2. **接 LLMJudge**：`pip install openai` + key，`Evaluator(..., judge=LLMJudge(api_key=...))`。
3. **接 CI / 回归**：失败报告喂给 `RegressionStore`，`prefix_boundary_set(n)` 生成边界集，随 Agent 一起演化。

### 外部 agent 接入（桥在框架侧，被测对象只读）

> [!IMPORTANT]
> 评估不污染被测对象：外部 agent 接入代码统一收口在 `agent_eval/integrations/`，被测项目目录零写入。
> 数据集已外置到仓库根 `data/`。

```
integrations/pi_bridge.ts        # TS 白盒桥：驱动 pi 真实 AgentSession（plan/llm 双模式）
integrations/pi_adapter.py       # Python 适配器：subprocess 调桥，PI_ROOT 定位被测源码
integrations/opencode_adapter.py # opencode 接入（黑盒 CLI）
integrations/deepseek_adapter.py # deepseek 接入（黑盒 CLI）
integrations/config/             # 各产品接入配置（opencode/dsh 的 slim 与 provider）
```

- 桥通过 `PI_ROOT` 环境变量（默认 `D:/MyFiles/agent-harness/pi-main`）动态 import 被测源码，**不写入、不修改被测项目**。
- **唯一评估入口（真实 LLM 模式）**：
  ```bash
  python -m agent_eval --agent pi --mode llm --datasets coding --k 2
  # → agent_eval/eval_pi_coding_llm.json（--output 可覆盖）
  ```
- `--mode llm`：pi Harness × 真实模型（正式评估）；`--mode plan`：确定性 reference_plan 注入（无 key 自检基线）。**评估前无需冒烟/基线先行**，直接 `--mode llm`；LLM 串行调用。

## 评估口径区分（三种被测对象，数字不可混比）

同一套 `Evaluator` + verifier/metrics，被测对象可插拔；但每次运行的**范围/判定权威不同**，跨运行比数字前必须看 `_meta`（agent_type / model / judge / dataset_scope / templates_run / k / sample_size）。

| agent_type | 决策来源 | 数据集范围 | judge | 数字含义 |
|---|---|---|---|---|
| `mock` | 硬编码完美执行者 | 全池（biz+coding） | dummy | 框架自检基线：验证器/数据/流程无 bug 时的上限 |
| `llm` | **真实 LLM 推理** (tool-calling) | 仅 memory backend | dummy/llm-real | 该模型×harness 在业务域的真实能力 |
| `pi` (plan) | 确定性 reference_plan 注入 | 仅 disk backend | dummy | pi Harness 层在固定决策下的表现 |
| `pi` (llm) | **真实 LLM 推理** | 仅 disk backend | dummy | **pi Harness × 真实模型** 在编码任务上的真实能力 |

四条硬规则：

1. 跨 `agent_type` 的 `Pass@k`/`Pass^k` 不可直接比较；同 `agent_type` 不同 `dataset_scope`/`k`/`mode` 也不可比。
2. 主判据永远是**确定性环境状态验证**（二元）；`judge` 分数是附加质量维度（0/1 与 0~1 尺度不同）。
3. 模板 id 跨目录可能同名异义（`data/base/` 与 `data/biz/` 均含 `base_clarify_001`），须以 `dataset_scope` 区分。
4. **工具面不限定（默认满血评估）**：`available_tools` 是声明性字段，不参与判定；被测 agent 用其完整工具面完成任务是**允许的且被计入真实能力**。横向对比时工具面差异如实反映在分数里。

## 依赖

- 运行时：**纯标准库**（零依赖）。
- 开发：`pytest>=8`（见 `requirements.txt`）。
- 可选（接入外部 agent）：`node>=22`（`--experimental-strip-types` 跑桥，无需额外 npm 包）。
