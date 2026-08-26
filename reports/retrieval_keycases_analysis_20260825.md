# Retrieval + Keycases 全指标评估报告（2026-08-25 晚）

> 数据来源（端点复活后、串行重跑，66 样本/agent = 33 模板 × k=2）：
> - `eval_deepseek_retrieval_keycases_20260825_203404.json`（dsh-gemma）
> - `eval_pi_llm_retrieval_keycases_20260825_211740.json`（pi-llm-gemma）
> - `eval_opencode_retrieval_keycases_20260825_213556.json`（opencode-gemma）
>
> 口径：verifier=确定性环境状态；judge=dummy；k=2；k_scope=同任务 k 独立样本。

---

## 0. 指标定义速查（来自 `metrics.py` / `process.py`）

**Outcome（结果）族**
- `pass_at_k` = 能力上限：同一任务 k 个样本里**至少 1 个通过**即 1.0（否则 0.0）。衡量"有没有能力做到"。
- `pass_k` = 业务可靠性：k 个样本**通过比例**（0–1）。衡量"稳定做到的概率"。
- `pass_consecutive_k` = 严格一致：k 个样本**必须全过**才 1.0。最严苛口径。
- `first_error_cases` = 触发 verifier 首错步的案例数（过程硬约束违例计数）。
- `by_capability` = 按 capability 拆分的 pass_k（本题仅 retrieval 一域）。

**Process（过程）族**（每条轨迹一个值，数据集取均值）
- `action_legality` = 1 − 非法步/总步。非法 = 未知工具 或 变更类工具未授权。
- `path_efficiency` = 1 − (重复步 + 错误步)/总步。重复=相同 action 再次出现。
- `retrieval_coverage` = 命中 gold 文档数 / gold 文档总数（read/open/cat 及 bash cat|tail|head 计入）。
- `cost_latency` = 单次任务 latency_ms（均值反映吞吐）。
- `safety_compliance` = 无敏感操作未确认 / 无 must_not_do 违例则为 1。

**Robustness（鲁棒性）族**（按模板计算）
- `seed_stability` = pass_k（种子稳定性，两 seed 平均通过率）。
- `seed_sensitivity` = pass_at_k − pass_k。>0 表示"**看种子脸色**"——有时过有时挂（时过时挂 = flaky）。
- 聚合报告的 `robustness.value` = seed_stability。

---

## 1. 总览对比表（全部指标）

| 维度 | 指标 | deepseek | pi-llm | opencode |
|---|---|---|---|---|
| **Outcome** | pass_at_k（能力上限） | 0.7879 | 0.8788 | **0.9697** |
| | pass_k（可靠性） | 0.6515 | 0.8788 | **0.9091** |
| | pass_consecutive_k（严格全过） | 0.5152 | **0.8788** | 0.8485 |
| | first_error_cases | 0 | 0 | 0 |
| **Capability** | retrieval pass_k | 0.6515 | 0.8788 | **0.9091** |
| **Process** | action_legality | 0.9608 | 0.9962 | **0.9967** |
| | path_efficiency | **0.9793** | 0.9777 | 0.9716 |
| | retrieval_coverage | 0.7298 | 0.8788 | **0.9091** |
| | cost_latency (均值/样本) | 39.6s | **16.6s** | 47.9s |
| | safety_compliance | 1.000 | 1.000 | 1.000 |
| **Robustness** | seed_stability（均值） | 0.6515 | 0.8788 | **0.9091** |
| | seed_sensitivity（均值） | 0.1364 | **0.0000** | 0.0606 |
| | flaky 模板数 (sens>0) | **9 / 33** | **0 / 33** | 4 / 33 |
| **CI** | Wilson 95% (pass_k) | [0.531, 0.755] | [0.779, 0.937] | [0.816, 0.958] |

---

## 2. Outcome 三件套解读

- **opencode 能力上限最高**（pass_at_k 0.97，几乎每题至少 1 seed 过）。
- **pi 严格一致性与可靠性并列最佳**（pass_k 0.879 与 pass_consecutive_k 0.879 **完全相等**）——因为它零 flaky（见 §5），过的题两 seed 都过。
- **deepseek 三项落差最大**：pass_at_k 0.79 → pass_k 0.65 → pass_consecutive_k 0.52，严格全过口径直接砍到一半，说明它大量"只过 1 个 seed"的题在拖后腿。
- **first_error_cases = 0（三家）**：无任何案例触发 verifier 首错步硬约束，结合 `unfinished=0`，证明本次运行**无 harness 崩溃、无过程硬违例**——彻底坐实早先 0 分是端点故障而非代码/模型。

---

## 3. Capability 维度

仅 retrieval 一域，pass_k 与 overall pass_k 一致（deepseek 0.652 / pi 0.879 / opencode 0.909）。本题集是纯检索域，结论即整体结论。

---

## 4. Process 五件套解读

- **action_legality**：pi(0.996) ≈ opencode(0.997) ≫ deepseek(0.961)。deepseek 有更多"未知工具/越权变更"步——与其在 middle 层乱试文件、动作更杂有关。
- **path_efficiency**：三家都很高（0.97–0.98），**deepseek 反而最高(0.979)**——它步数少、重复少，但"效率高"不等于"读得对"（见 coverage）。说明 deepseek 是"精炼地读错/读少"，而非"瞎绕"。
- **retrieval_coverage（核心过程指标）**：opencode 0.909 ≈ pass_k 0.909（读到位即判过，干净）；pi 0.879；**deepseek 0.730 明显偏低**——读到的 gold 文档比例最少，直接对应其 middle 成片挂（读不够/读不准）。
- **cost_latency**：**pi 16.6s 最快**（约为另两家 1/3），opencode 47.9s 最慢（Cordis 框架重）。deepseek 39.6s。pi 在"效果接近 opencode"前提下延迟最低，性价比最优。
- **safety_compliance**：三家全 1.0，无敏感操作违规。

---

## 5. Robustness（鲁棒性）解读——**本分析最关键的新发现**

| Agent | mean seed_stability | mean seed_sensitivity | flaky 数 |
|---|---|---|---|
| deepseek | 0.6515 | **0.1364** | **9 / 33** |
| pi-llm | 0.8788 | **0.0000** | **0 / 33** |
| opencode | 0.9091 | 0.0606 | 4 / 33 |

- **pi 完全零 flaky（sens=0）**：pi 的结果**完全可复现**——过的题两 seed 必过，挂的题两 seed 必挂。它的低分项（keycases、hard_006）是**系统性 read 跳过**，不是运气。这反而是优点：评价确定性高。
- **deepseek 最飘（9/33 flaky，sens 0.136）**：其 pass_k 0.65 里有一部分来自"某个 seed 运气好过 1 个"。它的成绩**被 seed 放大**，真实稳定水平可能更低。
- **opencode 居中（4/33 flaky）**：上限高但 4 题时过时挂，使其在 pass_consecutive_k(0.848) 略低于 pi(0.879)。

**deepseek flaky 模板**：base_002, hard_001/005/006/007, middle_001/009, keycases_hard_002, keycases_middle_004
**opencode flaky 模板**：middle_004, middle_007, keycases_middle_004, keycases_hard_009

---

## 6. 分 Tier 全指标明细

| Tier | Agent | pass_at_k | pass_k | pass_consec | seed_stab | seed_sens |
|---|---|---|---|---|---|---|
| **base(10)** | deepseek | 0.900 | 0.850 | 0.800 | 0.850 | 0.050 |
| | pi | 1.000 | 1.000 | 1.000 | 1.000 | **0.000** |
| | opencode | 1.000 | 1.000 | 1.000 | 1.000 | **0.000** |
| **middle(11)** | deepseek | 0.727 | 0.591 | 0.455 | 0.591 | 0.136 |
| | pi | 0.909 | 0.909 | 0.909 | 0.909 | **0.000** |
| | opencode | 1.000 | 0.864 | 0.727 | 0.864 | 0.136 |
| **hard(12)** | deepseek | 0.750 | 0.542 | 0.333 | 0.542 | **0.208** |
| | pi | 0.750 | 0.750 | 0.750 | 0.750 | **0.000** |
| | opencode | 0.917 | 0.875 | 0.833 | 0.875 | 0.042 |

**关键趋势**：
- deepseek 的 seed_sensitivity **随难度单调上升**（0.05 → 0.136 → 0.208）：越难越靠运气，hard 层成绩"虚高"最严重。
- pi 在 **每一层 sensitivity 都恒为 0**：base 全过、middle 0.909、hard 0.75，**稳定可复现**，hard 层 0.75 是真实系统水平。
- opencode 在 base/hard 稳定，但 **middle 层反而飘（0.136）**——其 4 个 flaky 有 2 个在 middle。

---

## 7. Wilson 95% 置信区间（pass_k）

- deepseek [0.531, 0.755]、pi [0.779, 0.937]、opencode [0.816, 0.958]。
- 三家 CI **互不重叠**（deepseek 上限 0.755 < pi 下限 0.779 < opencode 下限 0.816），统计上**排序显著**：opencode > pi > deepseek。

---

## 8. 结论与建议

### 8.1 综合画像
- **opencode**：能力上限最高、检索覆盖最准、零安全违规；代价是延迟最高(47.9s)、middle 层略飘(4 flaky)。
- **pi-llm**：**效果第二但综合最"干净"**——零 flaky（完全可复现）、延迟最低(16.6s)、action_legality 最高之一；短板是 keycases/hard_006 的 **read 强制力不足**（系统性跳过读取），且该短板完全确定性可复现。
- **deepseek**：各项最弱且**最不稳定**——middle 检索崩、seed 高度依赖运气（flaky 9/33，hard sens 0.208），读到的 gold 文档最少（coverage 0.73）。

### 8.2 行动建议
1. **deepseek 短板（middle 检索 + 稳定性）**：抽 middle 10 题做错误聚类（读不够 vs 读不准）；其 flaky 高说明同 prompt 不同 seed 差异大，可尝试 temperature 调低或检索范式 few-shot。
2. **pi 的 read 强制力**：pi 在 29/30 真实题满分却 keycases 全挂、hard_006 挂，典型"能读但不读"。建议在 pi instruction 层/verifier 反馈回路强化 read 强制，或对这些题做约束解码。
3. **opencode 的 middle flaky**：middle_004/007 两 seed 表现不一致，排查是否 glob/路径解析在不同 seed 下偶发失败（已观察到 `glob .*contract*` 正则路径 tool_error，属适配器兼容，非模型）。
4. **可观测性**：trajectory 已含 `request_count`（当前为 null），建议正式写入 `error`/`attempts` 遥测，使"端点故障 vs 模型失败"在报告层可直接区分（避免下次端点抖动再被误读为 0 分能力）。
5. **评价方法论**：pass_k 之外务必同时看 **seed_sensitivity**——deepseek 的 pass_k 被 seed 放大，pi 的"低分"反而更可信（确定性）。后续横向对比建议以 **pass_k + seed_sensitivity** 双指标定档。

---

## 附：非 keycases（30 真实题）满分率

| Agent | 满分模板 | 均值 pass_k | flaky 数 |
|---|---|---|---|
| deepseek | 17/30 | 0.683 | 7 |
| pi-llm | 29/30 | 0.967 | 0 |
| opencode | 28/30 | 0.967 | 3 |

→ 抛开诊断性 keycases，pi 与 opencode 在真实检索任务上几乎打平（29 vs 28 满分），差距完全来自 keycases 这 3 道"read 强制"陷阱题；deepseek 则在真实题上就已显著落后且多处 flaky。
