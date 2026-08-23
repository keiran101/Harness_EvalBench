# agent_eval —— Agent 评估框架（零外部依赖）

按《Agent 评估顶层设计方案》（`../Agent评估顶层设计方案.md`，指导来源《AI Agents in Depth》第六章）实现的 6 层评估框架。**评估单元是 Task / 轨迹（episode），验证环境最终状态而非文本**（不是 QA）。

## 快速开始

```bash
# 无需任何 API key / 网络
python examples/run_demo.py        # 端到端 demo，输出 eval_output.json
python -m pytest tests/ -q         # 33 个测试
```

demo 输出（k=4，15 个 base 模板）：

| agent | Pass@k（能力上限） | Pass^k（可靠性） | Pass^k(strict) | 失败归因数 |
|---|---|---|---|---|
| reference | 1.00 | 1.00 | 1.00 | 0 |
| flaky | 1.00 | **0.25** | 0.00 | 45 |
| buggy | 0.20 | 0.20 | 0.20 | 48 |

> 核心论点演示：**只看 Pass@k 会把一个 flaky 系统误判为可上线**。头部分数高 ≠ 业务可靠。

## 6 层架构（对齐设计文档）

| 层 | 包/模块 | 对应设计文档 | 职责 |
|---|---|---|---|
| 0 数据模型 | `core.py` | §3 Task 范式 | `Step` / `Trajectory`（轨迹=评估单元）/ `VerificationResult` / `EvalReport`；评测单元统一为 `TaskInstance`（见数据集层） |
| 1 数据集 | `datasets/` | §7 + 规格 `docs/superpowers/specs/2026-08-23-dataset-design.md` | 参数化模板 + base 5 能力 + FAIL_TO_PASS/PASS_TO_PASS 双检 + 防泄漏 + Registry |
| 2 指标 | `metrics/` | §5 | `Pass@k`（上限）/ `Pass^k`（可靠性）/ strict 连续 k / 报告纪律 |
| 3 环境 | `environments/` | §6.1 | `ToolCallingEnv`：工具暴露、确定性状态验证、reset、瞬时失败注入 |
| 4 Judge | `judge/` | §8 | `DummyJudge`（离线规则化）/ `LLMJudge`（rubric+锚定+偏差校正结构，需 key） |
| 5 可观测性 | `observability/` | §4.3 | 轻量 trace（逐 step span）+ 通过率漂移检测 |
| 6 闭环 | `closure/` | §4.2/§7.9 | 坏例 → `RegressionStore`，trajectory-prefix 边界集 |
| 编排 | `evaluator.py` | §4.2 | 用例→环境→Agent→验证→Judge→报告，k 次独立采样 |

## 数据集层（base / Middle / hard）

- 三档按**步骤数/工具数**递增：base 1–2步/1工具、Middle 3–5步/2–3工具、hard 6+步/多工具+陷阱。
- **base 档 5 类基础 harness 能力**（每类 3 模板）：`tool_call` 工具调用正确性 · `state_read` 行动前读状态 · `error_recovery` 失败重试 · `clarify` 缺失信息反问 · `confirm` 危险动作前确认。
- **验证器双检**：`FAIL_TO_PASS`（问题真被解决）+ `PASS_TO_PASS`（没引入回归），全过才判成功，二元奖励。
- **评测单元 Schema（单一类型，v2）**：`TaskTemplate`（可复用模板）→ `TaskInstance`（实例化后唯一评测单元）。字段：`id/template_id/domain/capability[]/tier/difficulty/steps/tools/instruction/setup/params/available_tools/expected_outcome/must_do/must_not_do/verifier/grader/leak_guard/tags/expectation`。
  - `capability` 是**数组**（一个任务可考察多个能力）；`domain` 独立业务域；`difficulty`（easy/medium/hard）与 `tier`（结构复杂度）正交。
  - **硬否决 `must_not_do`**：任一为 False（不安全）即整体失败，对应"不可逆动作未经确认"等红线；与 `fail_to_pass`/`pass_to_pass` 并列。
  - `available_tools` 声明该任务暴露的工具面（防作弊+可复现）；`grader` 自描述评分方式（rule/llm/custom）。
  - 检查以 **check spec** 表达：`{"fn": <注册名>, "args": {...}}`，逻辑在 `datasets/checks.py` 的 `CHECK_REGISTRY`，故数据集文件可纯数据序列化。
- **数据集外置存储**：base 15 个模板已从代码拆出，存于 `agent_eval/datasets/data/base/*.json`（每能力一文件，版本可控、可 diff）。`DatasetRegistry.from_file/from_dir` 加载；`with_base()` 仍作为内置默认集。加载时自动 `wire_leak_guard`（canary/新鲜度/隔离）。
- **防泄漏红线（已接线）**：canary GUID（同时嵌入 instruction 作诱饵）+ 时间新鲜度 + 隔离标记 + 随机实例参数。可复用的是**环境的构造机制**，不是具体题目。

```python
from agent_eval.datasets.registry import DatasetRegistry
# 内置默认集
reg = DatasetRegistry.with_base()
# 或外置文件集（推荐增长方式）
reg = DatasetRegistry.from_dir("agent_eval/datasets/data/base")
inst = reg.instantiate("base_tool_call_001", seed=7)   # 参数化实例
result = reg.verify(inst, final_state, trajectory)      # 双检 + 硬否决
```

## 如何接入真实系统

1. **换真实 Agent**：实现 `run(instance, env) -> Trajectory`（或直接替换 `agents.py` 里的 mock）。轨迹里用 `Step.is_error` 标记不可接受动作，首个错误步归因即生效。
2. **接 LLMJudge**：`pip install openai` + key，`Evaluator(..., judge=LLMJudge(api_key=...))`。已内置 rubric 分维 + 加权结构，按 `judge/judge.py` 注释补真实调用。
3. **接 CI / 回归**：失败报告喂给 `RegressionStore`，`prefix_boundary_set(n)` 生成边界集，随 Agent 一起演化（闭环）。

## 依赖

- 运行时：**纯标准库**（零依赖）。
- 开发：`pytest>=8`（见 `requirements.txt`）。
