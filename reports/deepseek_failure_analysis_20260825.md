# DeepSeek 评估结果失败根因分析（2026-08-25 晚）

> 数据源：`results/eval_deepseek_retrieval_keycases_20260825_203404.json`
> （deepseek / dsh-gemma，33 模板 × k=2 = 66 样本，retrieval+keycases）
> 本报告聚焦 deepseek 单家的全部失败数据，定位失败原因。

---

## 1. 结论摘要

**DeepSeek 的失败不是"检索精度差"，而是"根本没读"——它在大量任务里只做了 glob/ls 列目录就直接作答，没有调用 read 去读文件内容。** 用框架正确的读取定义（`READ_TOOLS={read,open,cat,view,show}` + bash 的 cat/tail/head）重新逐轨迹分类后：

- **16/33 模板非满分**，推断出 **23 个失败 seed**。
- 其中 **14 个（61%）真实读取次数 = 0** → "列目录即作答"捷径失败。
- 仅 **9 个（39%）真实读到了内容但仍失败** → 读错文件 / 覆盖不全。

> ⚠️ **对早先综合报告的更正**：在 `retrieval_keycases_analysis_20260825.md` 里，我曾把 glob/ls 也算进"read-like"，得出"deepseek 读了但读不准（under-retrieval）"的判断。**那是错的**。glob/ls/find 在框架里是 DISCOVERY 工具、不计入 retrieval_coverage。纠正后，deepseek 的主导失败模式是 **"从不读取"**，与 pi 的 read-skip 属同一类根因（用列目录/先验知识代替读内容），而非独立的"精度缺口"。

---

## 2. 失败规模与推断方法

- 总样本 66 seed；pass_k=0.6515 → 约 **43 通过 / 23 失败**。
- 失败 seed 推断规则：pass_k=0.0 则两 seed 均失败；pass_k=0.5 则失败 1 个（取读取数更少/为 0 的那个）。
- 读取分类：把每步 action 归为 `read`（真读）/ `discover`（glob/ls/find 等列目录）/ `other`。**只有 `read` 计入 retrieval_coverage**。

---

## 3. 双因 Taxonomy

| 失败类型 | 失败 seed 数 | 占比 | 表现 |
|---|---|---|---|
| **A. 从不读取（glob-and-answer）** | 14 | **61%** | 只做 1 次 glob/ls 就作答，0 次 read |
| **B. 读了但读错/不全** | 9 | 39% | 有 read 动作，但命中错文件或覆盖不足 |

### 类型 A 典型（整题 0.0，两 seed 均 0 读）
- `hard_retrieval_002`：seed0/seed1 均 `steps=1, reads=0, discover=1` → 一次 glob 后直接作答。
- `hard_retrieval_009`：同上，两 seed 均 0 读。
- `middle_retrieval_005`：两 seed 均 `steps=1, reads=0` → 列目录即停。
- `keycases_hard_009`：两 seed 均 0 读（keycases 诊断题，正暴露此弱点）。

### 类型 B 典型（有读但仍挂）
- `base_retrieval_007`：seed0 读 2、seed1 读 3，仍两 seed 全挂 → 读的不是 gold 文档。
- `middle_retrieval_003`：seed1 读 2 仍挂（seed0 是 0 读）。
- `middle_retrieval_004`：两 seed 各读 2，仍全挂 → 读错对象。
- `hard_retrieval_007`：seed0 **读 43 个文件**仍挂（seed1 仅读 2 过）→ 狂读却漏掉正确的那个，属严重检索噪声。
- `middle_retrieval_009`：两 seed 读 19–26 个文件，仍 1 个 seed 挂。

---

## 4. 逐模板归因表（纠正后，每 seed 真实 reads/discovers）

| 模板 | tier | pass_k | seed0 (read/disc) | seed1 (read/disc) | 主因 |
|---|---|---|---|---|---|
| base_retrieval_002 | base | 0.5 | 1/2 | 2/1 | B（读但不足） |
| base_retrieval_007 | base | 0.0 | 2/1 | 3/1 | B（读错） |
| hard_retrieval_001 | hard | 0.5 | **0/1** | 6/7 | A（seed0 不读） |
| hard_retrieval_002 | hard | 0.0 | **0/1** | **0/1** | **A（两 seed 都不读）** |
| hard_retrieval_005 | hard | 0.5 | **0/1** | 5/2 | A（seed0 不读） |
| hard_retrieval_006 | hard | 0.5 | 2/1 | **0/1** | A（seed1 不读） |
| hard_retrieval_007 | hard | 0.5 | 43/7 | 2/1 | B（狂读漏对） |
| hard_retrieval_009 | hard | 0.0 | **0/1** | **0/1** | **A（两 seed 都不读）** |
| middle_retrieval_001 | middle | 0.5 | 3/1 | **0/1** | A（seed1 不读） |
| middle_retrieval_003 | middle | 0.0 | **0/2** | 2/1 | A+B 混合 |
| middle_retrieval_004 | middle | 0.0 | 2/1 | 2/1 | B（读错） |
| middle_retrieval_005 | middle | 0.0 | **0/1** | **0/1** | **A（两 seed 都不读）** |
| middle_retrieval_009 | middle | 0.5 | 19/2 | 26/3 | B（读多仍漏） |
| keycases_hard_002 | hard | 0.5 | **0/3** | 3/1 | A（seed0 不读） |
| keycases_middle_004 | middle | 0.5 | 3/1 | 1/2 | B（读不足） |
| keycases_hard_009 | hard | 0.0 | **0/1** | **0/2** | **A（两 seed 都不读）** |

加粗 = 0 真实读取（类型 A 证据）。

---

## 5. 与 pi / opencode 的对比（为何 deepseek 最弱）

三家都暴露过"跳过读取"这一共同弱点，但形态不同：

- **pi**：只在 keycases(3) + hard_006 上 skip-read；且 **seed_sensitivity=0（0/33 flaky）** → 失败完全确定性、可复现，是"指令遵从/read 强制力"的局部短板。
- **opencode**：最强，仅 4/33 flaky，偶发读漏 + 一次 glob 正则路径 tool_error。
- **deepseek**：
  1. **skip-read 最泛化**——A 类失败散布在 base/hard/middle/keycases 各层（hard_002/009、middle_005、keycases_hard_009 整题 0 读），不是局部现象；
  2. **叠加真实精度缺口**——B 类（读了但读错，含 hard_007 读 43 个仍漏）是 pi 没有的第二失败源；
  3. **最不稳定**——9/33 flaky，hard 层 seed_sensitivity 高达 0.208，成绩部分靠 seed 运气。

→ deepseek 的 pass_k 0.65 里，**~61% 的失败本可通过"老老实实 read"消除**（类型 A），属低成本可修复的指令遵从问题；剩余 ~39%（类型 B）才是真正的检索/定位能力短板。

---

## 6. 典型样本（middle_retrieval_003 seed0）

```
steps:
  1. glob:{"path":"docs/","pattern":"**/*"}        ← discovery
  2. pwsh:{"command":"Get-ChildItem -Path docs -Recurse"}  ← discovery
  3. glob:{"path":"docs","pattern":"**/*.md"}       ← discovery
answer: "I have found the 4 documents in docs/ and docs/guide/...
         Note: there are actually 5 files... it's likely docs/draft/old.md
         might be an extra or draft file."
```
→ 全程 0 次 read，仅凭列目录 + 先验就作答。retrieval_coverage=0，判挂。**这是类型 A 的教科书样本。**

---

## 7. 修复建议

1. **首要：堵住"不读"捷径（针对类型 A，占 61%）**
   - 在 deepseek 的 system prompt / 任务指令中**显式强制"必须先 read 目标文件内容再作答"**，参考 keycases 的 field_annotations 写法。
   - 或在 verifier 反馈回路里加入"未 read 即作答"的惩罚信号，倒逼模型调用 read。
   - 这类失败修复成本最低、收益最大（可把 pass_k 从 0.65 拉到 ~0.85+）。

2. **次级：提升检索定位精度（针对类型 B，占 39%）**
   - `hard_007` 读 43 个文件仍漏 → 检索策略噪声大，建议加入"先精确定位再读"的 few-shot。
   - `base_007 / middle_004` 读错对象 → gold 文档识别能力弱，可强化"依据指令中的文件名/关键词定位 gold"的提示。

3. **稳定性**：deepseek 高 flaky（尤其 hard 层）建议 temperature 调低，减少 seed 间波动；重跑时同 seed 复现性差也影响评价可信度。

4. **可观测性**：trajectory 已含 `request_count`（当前 null），建议写入 `error` 与 `read_action_count` 遥测，使"未读即答"在报告层可直接量化，不必再靠人工逐轨迹分类。
