# DeepSeek 检索评估：正确样本 vs 错误样本 对照分析（2026-08-25）

> 数据：`results/eval_deepseek_retrieval_keycases_20260825_203404.json`（33 模板 × k=2 = 66 轨迹）
> 配套：三 agent 总览 `retrieval_keycases_analysis_20260825.md`、早前失败报告 `deepseek_failure_analysis_20260825.md`

## 0. 方法（为什么这次能"正确 vs 错误"对照）

- **带标签分组**：`pass_k=1.0` 的模板其 2 条轨迹必过 → **正确组（34 条）**；`pass_k=0.0` 的模板其 2 条轨迹必挂 → **错误组（14 条）**；`pass_k=0.5` 的 **MIX（18 条）** 单独用作"同一任务内两条 seed 的对照"。
- **gold 真值还原**：从 `agent_eval/datasets/data/{retrieval_*,keycases}/*.json` 按 id 还原每个模板的 `gold_docs`（应读文件）与指令文本。
- **读取路径提取**：解析 `read:{file_path:...}` 与 `pwsh Get-Content ...`，统一正/反斜杠归一化（deepseek 在 Windows 上用 `gdpr\main.md`，须转成 `gdpr/main.md` 才能对上 gold）。
- **覆盖率定义**：`coverage = |实际读到 ∩ gold| / |gold|`（框架同义指标）。

---

## 1. 总览对照：正确组 vs 错误组

| 特征（轨迹均值） | 正确组 PASS (n=34) | 错误组 FAIL (n=14) | 解读 |
|---|---|---|---|
| **retrieval_coverage** | **1.000** | **0.256** | 对 gold 的命中率，决定性差距 |
| 命中 gold 文件数 / 应读数 | 2.41 / 2.40 | 0.93 / 3.10 | 错误组"该读 3.1 个只读到 0.9 个" |
| reads / 轨迹 | 2.50 | 1.43 | 正确组平均多读 1 个文件 |
| steps / 轨迹 | 4.06 | 2.00 | 错误组"走两步就答" |
| **errors / 轨迹** | **0.00** | **0.00** | 两侧都 0 报错 |
| latency (ms) | 34,793 | 33,398 | 几乎相同 |
| 指令含干扰项(distractor) | 53% | 71% | 错误组更易遇干扰 |
| 应读文件数 gold_n | 2.41 | 3.14 | 错误组任务本就更"重" |

**首要结论**：正确样本 = 乖乖读完 gold 文件（覆盖率 100%）；错误样本 = 没读够（覆盖率仅 26%）。失败是 **omission（不读/读漏）**，不是 commission（工具崩/超时）。

---

## 2. 决定性证据：同一任务内，覆盖率高的 seed 过、低的 seed 挂（MIX 9/9 一致）

`pass_k=0.5` 的 9 个模板，两条 seed 同任务同模型，唯一能翻转胜负的就是 coverage：

| 模板 | coverage / 两条 seed | 结果 |
|---|---|---|
| base_retrieval_002 | 0.5 / **1.0** | 读 1/2 挂，读 2/2 过 |
| hard_retrieval_001 | 0.0 / **1.0** | 0 读挂，全读 过 |
| hard_retrieval_005 | 0.0 / **1.0** | 0 读挂，全读 过 |
| hard_retrieval_006 | **1.0** / 0.0 | 全读 过，0 读挂 |
| hard_retrieval_007 | **1.0** / 0.5 | 全读 过，读半 挂 |
| middle_retrieval_001 | **1.0** / 0.0 | 全读 过，0 读挂 |
| middle_retrieval_009 | 0.75 / **1.0** | 读 3/4 挂，读 4/4 过 |
| keycases_hard_002 | 0.0 / **1.0** | 0 读挂，全读 过 |
| keycases_middle_004 | **1.0** / 0.33 | 全读 过，读 1/3 挂 |

**9/9 模板：覆盖率高的 seed 通过、低的 seed 失败。** 这排除了"指令措辞 / tier / seed 身份"作为失败主因——同一道题，读对了就过、没读就挂。

---

## 3. 失败三因 Taxonomy（gold 实证，14 条失败轨迹）

| 类型 | 数量 | 占比 | 表现 |
|---|---|---|---|
| **A. 完全跳过读取（0 reads）** | 9 | **64%** | 仅 `glob` 列目录即作答，从不 `read` |
| **B. 读了但覆盖不足（读错/漏读）** | 4 | **29%** | 有读动作，但漏掉 gold 文件 |
| **C. 读了全部 gold 却仍挂（内容未捕获）** | 1 | **7%** | 文件读到了，命令没把内容取到 |

典型样本：
- **A**：`middle_retrieval_005` 两 seed 都是 `glob` 后直接作答，0 次 `read`。
- **B**：`middle_retrieval_004` 两 seed 都读了 `init.sql / add_idx.sql`，**每次都漏 `arch.sql`**；`middle_retrieval_003` 漏读 `docs/guide/` 子目录；`base_retrieval_007` seed0 漏 `d.log`。
- **C**：`base_retrieval_007` seed0 用 `Get-Content a.log,b.log,c.log,d.log | Select-Object -Last 1` —— 管道把 4 个文件输出**折叠成 1 行**，实际只拿到 `d.log` 末行，内容没真正取到 → 虽文件级覆盖 4/4，答案仍错。

> **更正早前报告**：早前 `deepseek_failure_analysis_20260825.md` 写"61% 不读 / 39% 读错"，是**未用 gold 真值、且误把 glob/ls 算作读取**所致。gold 实证修正为 **64% / 29% / 7%（新增"读全但内容未捕获"亚型）**。

---

## 4. 错因到底和什么有关（相关性结论）

| 变量 | 关联强度 | 结论 |
|---|---|---|
| **retrieval_coverage（是否真读到 gold）** | ★★★★★ 决定性 | PASS 组 100% 覆盖；`0-read → FAIL` 精确率 **100%**、召回 **64%**；`read≥1 → PASS` 精确率 **87%**（余 13% 为读错） |
| 应读文件数 gold_n | ★★★ 放大器 | FAIL 3.14 > PASS 2.41：要读的多，越易漏 |
| 指令含干扰项 distractor | ★★★ 放大器 | FAIL 71% > PASS 53%；分 tier：base 30% / middle 82% / hard 92% 含干扰，失败率随之 10% / 27% / 25% 上升 |
| **tier 难度标签** | ✗ 非因果 | 同 hard 任务内 coverage 即可翻转 outcome；tier 失败率差异可由 distractor%/gold_n 解释，是**混淆变量** |
| **延迟 / 超时** | ✗ 无关 | PASS 34.8s ≈ FAIL 33.4s，失败不是等超时 |
| **工具报错** | ✗ 无关 | 两侧 errors/traj 均为 0，失败是 omission 不是工具崩 |

**一句话**：deepseek 的失败 **100% 由"检索覆盖率不足"决定**；gold 文件越多、指令干扰越强，越容易触发"跳过/读漏"。难度标签本身不因果，它只是与"干扰多、文件多"高度共线。

---

## 5. 修复建议（按性价比排序）

1. **堵"跳过读取"捷径（占 64%，成本最低收益最大）**：在 deepseek 系统提示显式强制"先 `read` 再作答"，或 verifier 对"未读即答"加硬否决 → 预计 `pass_k` 0.65 → 0.85+。
2. **提定位精度（29%）**：`middle_004` 恒漏 `arch.sql`、`middle_003` 漏子目录 → 加 few-shot / 引导"递归列目录后逐个读"。
3. **修 pwsh 命令构造（7%）**：`Get-Content a,b,c | Select -Last 1` 折叠问题 → 改为逐文件读取。
4. **降 flaky**：调低 temperature（hard 层 `seed_sensitivity=0.208`，部分靠 seed 运气过）。

---

## 6. 复跑脚本
- `scripts/_deepseek_coverage.py` — gold 实证覆盖率 + 失败 taxonomy（核心）
- `scripts/_deepseek_pass_vs_fail.py` — PASS/FAIL 特征均值 + tier/env 分布
- `scripts/_deepseek_recover_instr.py` — 模板 id → 指令/gold 还原
