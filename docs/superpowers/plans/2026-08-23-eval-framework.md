# Agent 评估框架 实现计划（Implementation Plan）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `D:\dev\eval\agent_eval\` 下交付一套零外部依赖、可运行的 Agent 评估框架，覆盖设计文档《Agent 评估顶层设计方案》的全部 6 层，其中数据集层（第 1 层）严格按已批准规格 `docs/superpowers/specs/2026-08-23-dataset-design.md` 实现。

**Architecture:** 以「Task 而非 QA」为范式（设计文档 §3）：评估单元是轨迹（Trajectory=Step 序列）。数据集层产出参数化、分档、防泄漏、带确定性验证器的 TaskInstance；环境层消费它并暴露可程序化验证的状态；指标层从轨迹算 Pass@k/Pass^k/首个错误步；Judge 层可插拔（Dummy 默认、LLM 可接）；可观测性与闭环层把失败沉淀为回归集。各组件边界清晰、可独立测试。

**Tech Stack:** Python 3.13（managed venv，隔离），仅标准库 + pypdf（仅用于 PDF 抽取，运行时不依赖）。零网络、零 API key 即可跑通 demo。

## Global Constraints

- 评估单元是 **Task / Trajectory（episode）**，不是 QA 单轮——验证**环境最终状态**而非文本（规格 §4/§7.4）。
- 三档按**步骤数 / 工具数递增**：base 1–2步/1工具、Middle 3–5步/2–3工具、hard 6+步/多工具（规格 §2）。
- 验证器必须 **FAIL_TO_PASS + PASS_TO_PASS 双检**，二元奖励，确定性代码校验优先于 LLM-Judge（规格 §5/§8.1）。
- 防泄漏：随机实例参数 + canary GUID + 时间新鲜度 + 评估集题目与训练数据隔离（规格 §6 红线）。
- 数据集层作为独立包 `agent_eval/datasets/`，复用 `core` 的 `EvalCase`/`Trajectory`/`Step` 数据模型概念，但不反向依赖 demo 逻辑（规格 §8）。
- 报告必须写清 k 口径、样本量、环境差异、未完成部分（设计文档 §5.4）。
- 每次任务独立可测、频繁 commit（superpowers 纪律）。

---

## File Structure

```
agent_eval/
  agent_eval/
    core.py            # EvalCase / Step / Trajectory / EvalReport / VerificationResult（数据模型，被所有层依赖）
    datasets/
      __init__.py
      templates.py     # TaskTemplate / TaskInstance / param_schema / instantiate()
      capabilities.py  # base 档 5 类能力模板定义（tool_call/state_read/error_recovery/clarify/confirm）
      verifier.py      # FAIL_TO_PASS / PASS_TO_PASS 双检
      anti_leak.py     # canary GUID / 随机参数 / 时间新鲜度 / 隔离标记
      registry.py      # DatasetRegistry：版本化/标签/防泄漏标记/过滤
      mocks.py         # 用于 demo 的 mock 环境与 mock agent（零依赖）
    metrics/
      __init__.py
      metrics.py       # Pass@k / Pass^k / first_error_step / 报告纪律
    environments/
      __init__.py
      tool_env.py      # ToolCallingEnv：暴露工具/状态、reset、确定性验证器接口
    judge/
      __init__.py
      judge.py         # Judge 抽象 / DummyJudge / LLMJudge(结构+偏差校正占位)
    observability/
      __init__.py
      trace.py         # 轻量 tracing hook + 简单 drift 检测
    closure/
      __init__.py
      regression.py    # bad case → 回归/边界测试集沉淀
    evaluator.py       # 编排：用例→环境→Agent→指标→Judge→报告
  examples/
    run_demo.py        # 端到端零依赖 demo，输出 eval_output.json
  tests/
    test_datasets.py
    test_metrics.py
    test_verifier.py
  README.md
  requirements.txt
```

---

## Task 1: 核心数据模型（core.py）

**Files:** Create `agent_eval/agent_eval/core.py`

**Interfaces:** 被所有后续任务依赖。定义：`EvalCase(id, tier, capability, instruction, setup, expectation)`、`Step(action, observation, state_before, state_after, is_error)`、`Trajectory(steps: list[Step])`、`VerificationResult(passed: bool, fail_to_pass: dict, pass_to_pass: dict)`、`EvalReport(...)`。

- [ ] **Step 1: Write failing test** (`tests/test_core.py`): 构造 Trajectory 含 5 步，断言 `first_error_step(traj)` 返回首个 `is_error=True` 的索引。
- [ ] **Step 2: Run test → FAIL**（core 未定义）。
- [ ] **Step 3: Implement core.py** 含上述类与 `first_error_step` 辅助函数。
- [ ] **Step 4: Run test → PASS**。
- [ ] **Step 5: Commit** `feat: add core data models (EvalCase/Trajectory/Step)`.

## Task 2: 参数化模板与实例化（datasets/templates.py）

**Files:** Create `agent_eval/agent_eval/datasets/templates.py`

**Interfaces:** Consumes: `core.EvalCase`. Produces: `TaskTemplate`、`TaskInstance`、`instantiate(tid, seed) -> TaskInstance`、`param_schema` 随机生成。

- [ ] **Step 1: Write failing test**: 同模板不同 seed 生成的两个实例，其随机参数值（如 `[NAME]`）互不相同。
- [ ] **Step 2: Run → FAIL**。
- [ ] **Step 3: Implement** `TaskTemplate`(含 `param_schema` 字段与随机规则)、`instantiate()` 用 `random.Random(seed)` 填充槽位。
- [ ] **Step 4: Run → PASS**。
- [ ] **Step 5: Commit** `feat: parametric task templates + instantiate`.

## Task 3: base 档 5 类能力模板（datasets/capabilities.py）

**Files:** Create `agent_eval/agent_eval/datasets/capabilities.py`

**Interfaces:** Consumes `templates.TaskTemplate`. Produces 5 个 base 模板集合（每类 ≥3 个），capability ∈ {tool_call, state_read, error_recovery, clarify, confirm}，tier=base，steps/tools 符合 §2。

- [ ] **Step 1: Write failing test**: `list_base_templates()` 返回 5 类、每类 ≥3，全部 tier=='base' 且 steps<=2。
- [ ] **Step 2: Run → FAIL**。
- [ ] **Step 3: Implement** 5 类模板（含 instruction 槽、setup 初始状态、verifier 双检定义）。
- [ ] **Step 4: Run → PASS**。
- [ ] **Step 5: Commit** `feat: base-tier capability templates (5 classes)`.

## Task 4: 验证器双检（datasets/verifier.py）

**Files:** Create `agent_eval/agent_eval/datasets/verifier.py`

**Interfaces:** Consumes `core.VerificationResult`、TaskInstance 的 `verifier` 定义、环境 `final_state`。Produces `verify(instance, final_state) -> VerificationResult`（FAIL_TO_PASS 与 PASS_TO_PASS 全过才 passed=True）。

- [ ] **Step 1: Write failing test**: 对「正确完成」实例 verify→passed=True；对「未完成」→FAIL_TO_PASS 不过→False；对「表面完成（状态错）」→PASS_TO_PASS 不过→False。
- [ ] **Step 2: Run → FAIL**。
- [ ] **Step 3: Implement** 双检逻辑（每个 check 是可调用谓词，作用于 final_state）。
- [ ] **Step 4: Run → PASS**。
- [ ] **Step 5: Commit** `feat: FAIL_TO_PASS/PASS_TO_PASS verifier`.

## Task 5: 防泄漏（datasets/anti_leak.py）

**Files:** Create `agent_eval/agent_eval/datasets/anti_leak.py`

**Interfaces:** Produces `make_canary() -> str(GUID)`、`inject_canary(text, canary)`、`is_leaked(text, canary)`、`fresh_after(cutoff_date)` 辅助、`mark_isolation(template)`。

- [ ] **Step 1: Write failing test**: `is_leaked` 在含 canary 文本返回 True、不含返回 False；`inject`/`make_canary` 往返一致。
- [ ] **Step 2: Run → FAIL**。
- [ ] **Step 3: Implement** 上述函数（canary 用 `uuid.uuid4().hex`）。
- [ ] **Step 4: Run → PASS**。
- [ ] **Step 5: Commit** `feat: anti-leak (canary/random/freshness/isolation)`.

## Task 6: Dataset Registry（datasets/registry.py）

**Files:** Create `agent_eval/agent_eval/datasets/registry.py`

**Interfaces:** Consumes templates + anti_leak。Produces `DatasetRegistry`：`register(template)`、`list_templates(tier=,capability=)`、`instantiate(tid, seed)`、`verify(...)`、版本号、`leak_guard` 元数据扫描。

- [ ] **Step 1: Write failing test**: 注册 base 5 类后，`list_templates(tier='base')` 返回全部 base；`instantiate` 带 `leak_guard` 元数据；按 capability 过滤生效。
- [ ] **Step 2: Run → FAIL**。
- [ ] **Step 3: Implement** registry，整合前 5 个任务。
- [ ] **Step 4: Run → PASS**。
- [ ] **Step 5: Commit** `feat: DatasetRegistry (version/tags/leak-markers)`.

## Task 7: 指标层（metrics/metrics.py）

**Files:** Create `agent_eval/agent_eval/metrics/metrics.py`

**Interfaces:** Consumes `core.Trajectory` + 多次运行结果。Produces `pass_at_k(results, k)`、`pass_consecutive_k(results, k)`、`first_error_step(traj)`（已在 core 辅助，此处包装为指标报告）、`summarize(reports)` 含 k 口径/样本量/环境差异/未完成部分。

- [ ] **Step 1: Write failing test**: 给定 3 次运行（成/败/成），`pass_at_k(...,2)==1.0`、`pass_consecutive_k(...,3)` 按连续性计算；报告含样本量。
- [ ] **Step 2: Run → FAIL**。
- [ ] **Step 3: Implement** 指标与报告纪律。
- [ ] **Step 4: Run → PASS**。
- [ ] **Step 5: Commit** `feat: metrics Pass@k / Pass^k / first-error-step`.

## Task 8: 评估环境层（environments/tool_env.py）

**Files:** Create `agent_eval/agent_eval/environments/tool_env.py`

**Interfaces:** Consumes `core.EvalCase`/`TaskInstance`。Produces `ToolCallingEnv`：`reset(setup)`、`call_tool(name, args) -> observation`、`get_state()`、`is_terminal()`。确定性、可 reset 到干净初始状态。

- [ ] **Step 1: Write failing test**: `reset` 后 `get_state()` 等于 setup；调用合法工具后状态按预期变更；非法工具抛错。
- [ ] **Step 2: Run → FAIL**。
- [ ] **Step 3: Implement** 内存状态机 + 工具注册表。
- [ ] **Step 4: Run → PASS**。
- [ ] **Step 5: Commit** `feat: tool-calling evaluation environment`.

## Task 9: Judge 层（judge/judge.py）

**Files:** Create `agent_eval/agent_eval/judge/judge.py`

**Interfaces:** Produces `Judge` 抽象、`DummyJudge`（规则化评分，零依赖）、`LLMJudge`（结构：rubric + 锚定 + 三类偏差校正占位 + 失败归因输出），可插拔。

- [ ] **Step 1: Write failing test**: `DummyJudge.score(traj)` 返回结构化评分含 `failure_category` 与 `first_error_step`；`LLMJudge` 接口签名存在且可被 DummyJudge 替换。
- [ ] **Step 2: Run → FAIL**。
- [ ] **Step 3: Implement** 抽象 + Dummy + LLM 结构（LLM 调用留 `NotImplementedError` 当无 key）。
- [ ] **Step 4: Run → PASS**。
- [ ] **Step 5: Commit** `feat: Judge layer (Dummy + LLM structure)`.

## Task 10: 可观测性（observability/trace.py）

**Files:** Create `agent_eval/agent_eval/observability/trace.py`

**Interfaces:** Produces `Trace`/`Span`（轻量）、`record_step(traj)`、`detect_drift(history)` 简单阈值漂移检测。供 evaluator 挂分。

- [ ] **Step 1: Write failing test**: 记录一条 trajectory 后 `detect_drift` 在通过率骤降时返回告警。
- [ ] **Step 2: Run → FAIL**。
- [ ] **Step 3: Implement** 轻量 trace + drift。
- [ ] **Step 4: Run → PASS**。
- [ ] **Step 5: Commit** `feat: lightweight observability + drift`.

## Task 11: 闭环（closure/regression.py）

**Files:** Create `agent_eval/agent_eval/closure/regression.py`

**Interfaces:** Consumes 失败 `TaskInstance` + `Trajectory`。Produces `RegressionStore`：`add_badcase(instance, traj)`、`list_regression()`、`prefix_boundary_set(n)`（固定前 n 步生成边界集）。

- [ ] **Step 1: Write failing test**: 加入 2 个 bad case 后 `list_regression()` 返回 2；`prefix_boundary_set(2)` 生成固定前 2 步的边界用例。
- [ ] **Step 2: Run → FAIL**。
- [ ] **Step 3: Implement** regression store + prefix 边界集。
- [ ] **Step 4: Run → PASS**。
- [ ] **Step 5: Commit** `feat: closure regression store + prefix boundary`.

## Task 12: 编排 + 端到端 demo（evaluator.py + examples/run_demo.py）

**Files:** Modify `agent_eval/agent_eval/evaluator.py`、Create `agent_eval/examples/run_demo.py`

**Interfaces:** Consumes 全部层。Produces `Evaluator.run(registry, env_factory, agent, k)` → `EvalReport`；demo 用 mock 环境 + DummyJudge + base 档模板端到端跑通，输出 `eval_output.json`。

- [ ] **Step 1: Write failing test**: `Evaluator` 对已知 mock agent（Reference/Flaky/Buggy）产出与规格一致的 Pass@k/Pass^k 与首个错误步。
- [ ] **Step 2: Run → FAIL**。
- [ ] **Step 3: Implement** evaluator 编排 + mock agent + 更新 run_demo.py。
- [ ] **Step 4: Run demo**: `python examples/run_demo.py` 零依赖通过，生成 eval_output.json。
- [ ] **Step 5: Commit** `feat: evaluator orchestration + zero-dep demo`.

## Task 13: 文档与自检（README + 全局测试）

**Files:** Modify `agent_eval/README.md`、`agent_eval/requirements.txt`；Run 全量 `tests/`。

- [ ] **Step 1: 全量测试 PASS**：`python -m pytest tests/ -q`。
- [ ] **Step 2: 写 README**：架构图、6 层对应、如何扩展真实 Agent/LLMJudge、防泄漏红线。
- [ ] **Step 3: Commit** `docs: README + green test suite`.

---

## Self-Review

1. **Spec coverage:** 三档分层(§2)→Task2/3；base 5 能力(§3)→Task3；Task 解剖(§4)→Task2；双检(§5)→Task4；防泄漏(§6)→Task5；Registry(§7)→Task6；接口(§8)→全部复用 core；验收(§9)→Task1-6 测试覆盖。其余 5 层由 Task7-12 按设计文档 §5/§6/§8/§4.3/§4.2 实现。
2. **Placeholder scan:** 无 TBD；LLMJudge 真实调用显式 `NotImplementedError`（有 key 才启用），非占位敷衍。
3. **Type consistency:** `TaskInstance`/`VerificationResult`/`EvalReport` 命名在 Task1-6 与 Task12 一致；`instantiate(tid, seed)` 签名在 Task2/6 一致。
