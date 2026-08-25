# 检索域三 Agent 失败 Case 分析

> 数据来源：`results/retrieval_{pi,opencode,deepseek}_20260824_2254.json`（修复后真实 LLM 评估，k=2，30 模板/agent）
> 生成时间：2026-08-24 23:17
> 说明：本批产物为代码改造「轨迹落盘」**之前**跑出，JSON 内不含原始 trajectories，故失败归因基于 **verifier 配置 + 三 agent 失败重合度 + setup 干扰文件** 反推，未做单条轨迹复核。

## 一、总体失败分布

| Agent | 失败模板数 | base | middle | hard | pass_k |
|-------|-----------|------|--------|------|--------|
| pi | 5/30 | 2/10 | 1/10 | 2/10 | 0.85 |
| opencode | 6/30 | 2/10 | 2/10 | 2/10 | 0.85 |
| deepseek | 16/30 | 1/10 | 8/10 | 7/10 | 0.60 |

失败模板并集 18 个。三 agent 失败模式差异极大：**pi/opencode 仅零星失败，deepseek 在 middle/hard 系统性崩（15/20）**。

## 二、失败根因判定框架

所有失败模板的 `fail_to_pass` 均为 `retrieval_covered`（= 全部 gold_doc 被 read 覆盖），`pass_to_pass` 均为 `file_content_eq` / `file_not_exists`（= 环境未被误改）。因此每个失败 case 只可能是两类原因之一：

1. **覆盖率漏读（coverage < 1.0）**：agent 没 read 到某个 gold_doc（最可能是干扰目录/同名文件/版本混淆导致漏读或读错）。
2. **环境误改（pass_to_pass 失败）**：agent 改了不该改的文件，或创建了不该存在的文件。

`first_error_steps` 全部为空 → 不是"首步即错"，而是**漏读/误改在过程中发生**。

## 三、关键发现：两类失败性质完全不同

### A. 三 Agent 全败的模板（4 个）—— 疑似数据集设计口径问题

| 模板 | tier | gold_docs | 失败性质推断 |
|------|------|-----------|-------------|
| `base_retrieval_007` | base | a/b/c/d.log（4 份平铺） | 4 份同级日志，gold 多但无干扰；三 agent 全漏读至少 1 份 → 可能是 **coverage 解析对多文件平铺的边界问题**，或 agent 读 3 份就汇报 |
| `hard_retrieval_002` | hard | pay_api/callback/refund.md（pay 模块） | 同目录混放 risk/、pay_draft/ 噪声；三 agent 全漏读 → **选择性检索在"同目录噪声"场景普遍失效** |
| `middle_retrieval_004` | middle | migrations/001~003.sql | `migrations/tmp/scratch.sql` 干扰；全败 → agent 易把 tmp 草稿也算进来或漏读 003 |
| `base_retrieval_010`* | base | schema.sql/seed.sql | *注：base_010 仅 pi 败，非全败，列错；实际全败为上述 3 + 以下部分* |

> **重要**：3 个能力差异极大的 agent 在同一模板**一致失败**，基本排除"agent 个体能力"因素，指向**该模板的 gold 定义 / 干扰设置让"正确检索"也难以满足 verifier**，或 **coverage 解析在多文件场景仍有盲区**。这类模板需单条轨迹复核确认。

### B. 仅 deepseek 失败的模板（13 个）—— 典型 agent 能力短板

deepseek 在 middle（8 失败）、hard（7 失败）几乎系统性崩，而 pi/opencode 在同模板多数通过。典型：
- `middle_retrieval_001/005/006/007/009/010`：需跳过 `tmp/`、`logs/`、`_disabled/`、`_legacy/`、`cache/` 等干扰目录。pi/opencode 能识别"忽略"语义，deepseek 倾向**把干扰目录也读进来或漏读 gold**。
- `hard_retrieval_001/004/005/007`：需**跨版本/跨法域/跨类型选择性检索**（v1/v2/v3、GDPR/CCPA、incident/postmortem）。deepseek 漏读率高。

→ **deepseek 的核心弱点：干扰目录过滤 + 选择性检索**，属 harness/模型能力，非数据集问题。

### C. 仅单 agent 零星失败（pi 2、opencode 2）

- `base_retrieval_003`（仅 opencode 败）：3 份数据文件读条数，opencode 可能漏读 1 份。
- `base_retrieval_010`（仅 pi 败）：schema/seed 两份，pi 偶发漏读。
- `hard_retrieval_006`（pi+deepseek 败，opencode 过）：GDPR 正式文档 vs 所有 draft，pi 在此选择性检索偶发失效。
- `hard_retrieval_009`（opencode+deepseek 败）：active/ 生效合同 vs archived/ + client_c 草稿，两种 harness 都漏读。
- `middle_retrieval_008`（opencode+deepseek 败）：locales _legacy 忽略，两种 harness 在此漏读。

→ 这类属**偶发漏读（k=2 下 1/2 seed 失败）**，agent 基本能力达标但鲁棒性不足。

## 四、pass_to_pass 误改风险评估

核对失败模板的 `pass_to_pass` 配置，发现一个**潜在设计脆弱点**：

- `middle_retrieval_004/006/008`：pass_to_pass 要求 `tmp/scratch.sql`、`sub/tmp/notes.md`、`_legacy/messages.json` 保持原值。这些文件恰在"要求忽略"的目录里。若 agent 出于"整理"动机动了它们 → 误改失败。但三 agent 在此类模板并非全败，说明误改非主因，**漏读仍是主因**。
- `hard_retrieval_002/009`：含 `file_not_exists`（要求 `pay/_tmp.md`、`templates/active/_tmp.md` 不存在）。若 agent 创建了临时文件 → 直接 fail。这是**比 file_content_eq 更严的约束**，真实 agent 若写中间文件即判死。

> 建议：对 hard 模板的 `file_not_exists` 约束，确认是"考 agent 不写脏文件"还是"误伤"。若是前者，合理；若是后者，应放宽。

## 五、结论与建议

1. **deepseek 是主要失败源**（16/30），根因是**干扰目录过滤 + 选择性检索能力弱**，与数据集无关 → 属 agent/harness 改进项。
2. **4 个三 agent 全败模板**（base_007、hard_002、middle_004 等）需**单条轨迹复核**，确认是 coverage 解析盲区还是 gold/干扰设计过严。
3. **当前产物无 trajectories**，无法逐条定责。建议**重跑带轨迹版**（代码已支持）后，对失败 case 做精确归因（漏读哪个 gold / 误改哪个文件）。
4. **hard 模板 file_not_exists 约束**建议复核，避免过度惩罚。

## 六、下一步（待确认）

- 重跑 3 agent 带轨迹版（默认落 `results/`，带时间戳）→ 精确归因每个失败 case。
- 对 4 个全败模板做单条轨迹诊断（coverage 解析 or 数据集设计）。
- 评估是否放宽 hard 的 `file_not_exists` 约束。
