# 数据集层设计规格（Dataset Layer Spec）

> **状态**：已批准（brainstorming 设计阶段，写作于 2026-08-23）
> **指导来源**：《AI Agents in Depth》中文版第六章「Agent 的评估」+ 《Agent 评估顶层设计方案》（`Agent评估顶层设计方案.md` §7）
> **定位**：整个评估系统的「地基中的地基」（设计文档 §2 重点 #5）。本规格是 **6 层路线图中的第 1 层（数据集层）**，数据集优先于指标/环境/Judge 实现。
> **核心问题**：*怎么判断 Agent 变好了还是变差了？* —— 数据集决定「测什么」，没有它指标与 Judge 无处附着。

---

## 1. 目标与范围

### 1.1 目标
交付一套**可分档（base / Middle / hard）、可参数化、防泄漏、带确定性验证器**的 Agent Task 数据集，作为后续指标层、环境层、Judge 层与闭环的共享输入。

### 1.2 本子项目范围（In Scope）
- 数据集**三档分层模型**（按步骤数 / 工具数递增）
- **base 档**：基础、简单的 harness 共性能力探针（5 类，见 §3）
- 统一的 **Task 解剖结构**与参数化模板机制（§4）
- **验证器双检**规范：FAIL_TO_PASS + PASS_TO_PASS（§5）
- **防泄漏**专项设计：随机实例参数 + canary GUID + 时间新鲜度 + 隔离红线（§6）
- **Dataset Registry**：版本化、复杂度标签、防泄漏标记（§7）

### 1.3 不在本子项目范围（Out of Scope）
- 指标计算（Pass@k / Pass^k / 首个错误步）→ 见 #18
- 评估环境运行器（工具调用型环境、reset 机制）→ 见 #19
- LLM-Judge 实现 → 见 #20
- 可观测性 / 在线采样 → 见 #21
- bad case 回流闭环 → 见 #22
- Middle / hard 档的**具体任务内容**仅给规范与示例，批量填充在后续迭代；本规格先把 base 档做扎实。

---

## 2. 三档分层模型（按步骤数 / 工具数递增）

用户决策：**三档按「步骤数 / 工具数」递增划分**，base = 基础、简单的 harness 能力。

| 档 | 步骤数 | 工具数 | 内容定位 | 失败指向的改进方向 |
|---|---|---|---|---|
| **base** | 1–2 | 1 | 单一基础能力探针（一次工具调用或一次状态读/一次澄清） | 某项 harness 基础能力缺失 |
| **Middle** | 3–5 | 2–3 | 2–3 项能力组合 + 多步依赖（A→B 依赖） | 规划 / 信息整合不足 |
| **hard** | 6+ | 多 | 长程状态管理 + 陷阱任务（欺骗/误导/越权） | 长序列推理 / 抗误导 / 危险前确认 |

> 复杂度分层的核心价值是**诊断性**（设计文档 §7.3）：某一档失败集中，指向明确的改进手段，而非笼统「分数低」。

---

## 3. base 档能力目录（基础、简单）

base 每个任务仅测**一项** harness 基础能力，简单、单点、可机械化验证。共 5 类：

| 能力 ID | 名称 | 任务示例（参数化槽用 `[ ]` 标注） |
|---|---|---|
| `tool_call` | 工具调用正确性 | 「用 `[TOOL]` 工具把 `[ENTITY]` 的 `[FIELD]` 改为 `[VALUE]`」——验证器查最终状态字段值 |
| `state_read` | 行动前读环境状态 | 「先读取 `[ENTITY]` 当前 `[FIELD]`，再据此决定下一步」——验证器确认 Agent 先 GET 后动，未凭假设 |
| `error_recovery` | 错误恢复与重试 | 首次工具调用故意返回错误，验证器确认 Agent 重试/换参后达成目标，未崩溃/死循环 |
| `clarify` | 信息缺失时反问 | 指令缺关键参数（如未给 `[FIELD]` 值），验证器确认 Agent 先反问而非臆造 |
| `confirm` | 危险动作前确认 | 指令要求删除/对外发送，验证器确认 Agent 在执行不可逆动作前先请求确认 |

> base 档数量少而精：每类先给 3–5 个参数化模板，足以探针该能力。

---

## 4. Task 解剖结构（统一 schema）

每个任务 = 一个**可实例化的参数化模板**。字段：

```yaml
TaskTemplate:
  id:            string            # 全局唯一，含 tier 前缀，如 base_tool_call_001
  tier:          enum              # base | Middle | hard
  capability:    enum              # tool_call | state_read | error_recovery | clarify | confirm | ...
  steps:         int               # 期望步骤数（用于分档与诊断）
  tools:         int               # 涉及工具数
  instruction:   string            # 含参数槽，如 "将 [NAME] 的电话改为 [PHONE]"
  setup:         object            # 环境初始状态（确定性、可 reset）
  param_schema:  object            # 参数槽定义 + 随机生成规则（防泄漏）
  verifier:
    fail_to_pass:  list<check>     # 修复前失败、修复后必须通过（证明问题被解决）
    pass_to_pass:  list<check>     # 前后都必须通过（证明未引入新 bug）
  leak_guard:
    canary:       string|null      # 若模型输出即证明泄漏
    fresh:        bool             # 是否依赖时间新鲜度（训练截止后）
    isolation:    bool             # 题目与训练数据隔离标记
  tags:          list<string>      # 能力维度/场景/边界 标签
```

**实例生成**：`instantiate(template, seed)` → `TaskInstance`（填充随机参数 + 固定初始状态）。验证基于**最终环境状态**而非文本（设计文档 §7.4），防「表面完成」。

---

## 5. 验证器设计（FAIL_TO_PASS / PASS_TO_PASS 双检）

源自 SWE-bench（设计文档 §7.4）：
- **FAIL_TO_PASS**：在错误初始状态下该检查失败；Agent 正确完成后通过。证明任务被真正解决、非侥幸。
- **PASS_TO_PASS**：无论 Agent 行为如何，该检查都应保持通过（如「未误删其他记录」「最终状态无脏数据」）。证明没引入回归。
- 一个任务**全部检查通过**才判定成功；二元奖励，确定性代码校验优先于 LLM-Judge（设计文档 §8.1「有严格格式/可执行断言时不用 Judge」）。

---

## 6. 防泄漏专项设计（红线）

评估集题目必须与训练数据严格隔离（设计文档 §7.7 红线）：
1. **随机实例参数**：`[NAME]`/`[ORDER_ID]`/`[DATE]` 等每次随机生成，无法回放固定序列。
2. **canary GUID**：敏感/探测任务嵌入唯一 GUID，模型若原样输出即证明泄漏。
3. **时间新鲜度**：hard 档尽量收录「模型训练截止日之后」的场景（对应 SWE-bench-Live 思路）。
4. **答案稀有性**：任务目标高度具体（如某精确字段值），难从训练数据原样出现。
5. **隔离红线**：可复用**环境的构造机制**（setup 生成逻辑），但**评估集具体题目**（已填充参数的实例）不得进入训练数据。

---

## 7. Dataset Registry

职责（设计文档 §4.4 组件清单）：
- **版本化**：每次数据集变更生成版本号，可复现历史评估。
- **复杂度标签**：tier / capability / steps / tools 维度索引，支持「只跑 base 档回归」。
- **防泄漏标记**：每个实例携带 `leak_guard` 元数据，CI 可自动扫描 canary / 重复题目。
- **参数化模板管理**：模板与实例分离，实例按需生成、不长期落盘敏感参数。

接口示意（供 #18/#19 消费）：
```python
class DatasetRegistry:
    def list_templates(tier=None, capability=None) -> list[TaskTemplate]
    def instantiate(tid: str, seed: int) -> TaskInstance
    def verify(instance: TaskInstance, final_state: dict) -> VerificationResult  # FAIL_TO_PASS & PASS_TO_PASS
```

---

## 8. 与整体框架的接口

- **输入侧**：Registry 产出 `TaskInstance`，交给评估环境（#19）作为 episode 起点。
- **输出侧**：环境跑完得到 `final_state` + `Trajectory`（含 Step 序列，供首个错误步归因 #18），Registry.verify 给出通过/失败 + 检查明细。
- **数据模型兼容**：复用现有 `agent_eval/core.py` 的 `EvalCase` / `Trajectory` / `Step` 概念，确保与已写 demo 的评估流水线对接，但数据集层本身作为独立包（`agent_eval/datasets/`），不反向依赖 demo 逻辑。
- **闭环接口**：失败实例 / 低分 trajectory 可被 #22 沉淀为回归/边界测试集。

---

## 9. 验收标准（本子项目 Done 的定义）

1. `DatasetRegistry` 可列出 base 档 5 类能力、每类 ≥3 个参数化模板。
2. `instantiate` 对同模板不同 seed 生成**参数互异**的实例（防泄漏验证通过）。
3. `verify` 对「正确完成 / 未完成 / 表面完成（状态错）」三种轨迹分别给出 FAIL_TO_PASS/PASS_TO_PASS 正确判定。
4. Registry 支持按 tier / capability 过滤，且每个实例携带 `leak_guard` 元数据。
5. 提供 1 个最小 demo：用 mock 环境跑通 base 档一个模板的实例化→验证，零外部依赖。

---

## 10. 假设与开放项

- **假设**：base 档先手工打磨少量高质量模板（用户认可「基础、简单」），Middle/hard 后续用模板批量铺量。
- **开放项**：人机交互型任务（渐进式信息透露、双控环境，设计文档 §6.1）是否纳入本数据集——目前 base 档以**工具调用型**为主，交互型在 hard 档再考虑。
- **开放项**：base 档是否引入「陷阱/边界」子任务——用户明确 base=简单，故 base 不含陷阱；陷阱归 hard。

---

## 11. 路线图映射（6 层，数据集优先）

| 序 | 层 | 任务卡 | 状态 |
|---|---|---|---|
| 1 | 数据集层 | #17（本规格） | 进行中（spec 已批准） |
| 2 | 指标体系层 | #18 | 待启动 |
| 3 | 评估环境层 | #19 | 待启动 |
| 4 | LLM-Judge 层 | #20 | 待启动 |
| 5 | 可观测性 + 在线采样 | #21 | 待启动 |
| 6 | 闭环化 | #22 | 待启动 |
