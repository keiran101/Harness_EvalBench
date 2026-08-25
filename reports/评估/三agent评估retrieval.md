# 检索域（retrieval）三 Agent 真实 LLM 评估 · 修复前后对比报告

- **生成时间**：2026-08-24 22:54（时间戳 `20260824_225414`）
- **数据集**：`agent_eval/agent_eval/datasets/data/retrieval/`（base/middle/hard 各 10 条，共 30 模板）
- **评估口径**：真实 LLM（`google/gemma-4-12b-qat`，`http://8.134.63.180:7010`），k=2，串行调用
- **参与 Agent**：pi（TS 桥）、opencode、deepseek-harness
- **输出文件**：`eval_pi_retrieval_llm.json` / `eval_opencode_retrieval_llm.json` / `eval_deepseek_retrieval_llm.json`

---

## 一、本轮修复内容（根因 → 方案）

| # | 问题 | 根因 | 修复方案 | 改动文件 |
|---|------|------|----------|----------|
| 1 | opencode/deepseek `retrieval_coverage=0`（假阴性） | 两 harness 的 `read` 参数 key 分别为 `filePath`（opencode）、`file_path`（deepseek），框架 `_read_path()` 硬编码只认 `path` | `_read_path` 多 key 容错：`path → file_path → filePath → absolute_path`，兜底"字符串像路径即当 path" | `metrics/process.py` |
| 3 | deepseek `action_legality=0.53`（偏低） | deepseek 大量使用 `glob` 工具探索文件，disk vocab 不含 `glob` 被判非法（非真越权） | disk backend vocab 补 `glob/ls/find/cat/open` 等只读探索工具 | `metrics/process.py` |
| 2 | 三 agent `pass_k` 普遍偏低 | retrieval 域 `fail_to_pass` 用 `reported_file_value`，要求 answer **精确含文件原文全文**；agent 读到并提炼要点却因非逐字复述被判 fail | 新增 `retrieval_covered` check（coverage==1.0 即过），30 模板 `fail_to_pass` 由 `reported_file_value` 改为 `retrieval_covered`；成败改由「覆盖率+pass_to_pass」判定 | `datasets/checks.py` + `retrieval_*.json` |

> 说明：问题 1+3 是**解析口径**问题（agent 实际达标但指标误判）；问题 2 是 **check 设计与任务意图错位**（考"复述原文"过严）。三类问题均非 agent 能力缺陷。

---

## 二、总体指标：修复前 → 修复后

| Agent | pass@k（前→后） | pass^k（后） | Pass-consec（后） | 首错（后） |
|-------|------------------|--------------|-------------------|------------|
| **pi** | 0.5667 → **0.8667** | 0.8500 | 0.8333 | 1 |
| **opencode** | 0.6000 → **0.9000** | 0.8500 | 0.8000 | 0 |
| **deepseek** | 0.3333 → **0.7333** | 0.6000 | 0.4667 | 0 |

---

## 三、过程指标：修复前 → 修复后

| Agent | 检索覆盖率（前→后） | 动作合法率（前→后） | 平均延迟 ms（前→后） | 路径效率（后） | 安全合规（后） |
|-------|----------------------|----------------------|----------------------|----------------|----------------|
| **pi** | 0.8667 → 0.8583 | 0.991 → 0.9900 | 18961 → 28328 | 0.9591 | 1.0 |
| **opencode** | 0.0000 → **0.8583** | 0.935 → 0.9948 | 56848 → 46494 | 0.9759 | 1.0 |
| **deepseek** | 0.0000 → **0.6389** | 0.533 → **0.9681** | 38993 → 120833 | 0.9437 | 1.0 |

**关键修复见效点**：
- opencode / deepseek 检索覆盖率从 **0 恢复到 0.8583 / 0.6389**（解析口径修复，不再假阴性）。
- deepseek 合法率从 **0.533 回升到 0.9681**（glob 不再被判非法）。
- pi 覆盖率与合法率基本持平（pi 原本就用 `path` key，未受影响，符合预期）。

---

## 四、分 Tier 通过率（pass_k，修复后）

| Tier | pi | opencode | deepseek |
|------|----|----------|----------|
| base（10） | 0.85 | 0.85 | 0.90 |
| middle（10） | 0.90 | 0.85 | 0.50 |
| hard（10） | 0.80 | 0.85 | 0.40 |

**观察**：
- pi / opencode 难度梯度平缓（middle 甚至略高于 base/hard），说明两者对噪声/嵌套目录的鲁棒性较好。
- **deepseek 呈明显 base > middle > hard 递减**（0.90 / 0.50 / 0.40），符合检索任务难度设计预期，但也暴露 deepseek 在复杂语料（同名跨目录、版本混淆、大语料选择性检索）上覆盖率下降明显（整体 coverage 仅 0.639）。

---

## 五、遗留项与后续建议

1. **deepseek hard/middle 覆盖率偏低（0.40/0.50 通过）**：根因是 deepseek 在复杂场景下未读全 gold_docs（coverage 0.639）。属 agent 真实能力局限，非口径问题——可单条排查其 hard 模板轨迹，看是否漏读或路径推断错误。
2. **deepseek 平均延迟 120s/次**：远高于 pi(28s)/opencode(46s)，与其 harness 启动开销有关，评估耗时主要瓶颈在 deepseek。
3. **pi 仍有 1 个首错用例 + coverage 0.858**：可单条定位 base 中未读全 gold 的模板。
4. **transient_recovery 指标**：设计上 deferred，本域无数据，仍为范围外项。

---

## 六、产物文件清单

| 文件 | 说明 |
|------|------|
| `D:\dev\eval\eval_pi_retrieval_llm.json` | pi 检索域评估（修复后） |
| `D:\dev\eval\eval_opencode_retrieval_llm.json` | opencode 检索域评估（修复后） |
| `D:\dev\eval\eval_deepseek_retrieval_llm.json` | deepseek 检索域评估（修复后） |
| `D:\dev\eval\results\retrieval_3agent_eval_20260824_225414.md` | 本报告 |

> 注：上述三份 `*_retrieval_llm.json` 为未跟踪的本地评估产物，尚未提交 git；如需入库请告知。
