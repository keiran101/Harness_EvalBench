# Agent 评估数据集扩充方案（coding 域）

> 目的：让数据集能**区分出 harness 性能**（现状：简单任务两极分化，看不出 pi Harness 的好/坏/中间态）。
> 依据：当前 coding 数据集静态构成分析 + pi 真实 LLM 评估实测（§2 已回填 2026-08-23）。
> 状态：**定稿**（§2 实测已回填；§3 扩充方向按实测修订）。

---

## 1. 现状诊断：为什么"评估不出 harness 性能"

### 1.1 数据集静态构成（coding 域 29 模板，4 文件）

| 维度 | 现状 | 问题 |
|---|---|---|
| tier | hard 10 / Middle 10 / base 9 | 结构分层有，但**难度靠步骤数堆叠**，非认知复杂度 |
| capability | tool_call 26 · state_read 18 · confirm 6 | **error_recovery=0、clarify=0**——5 类基础能力缺 2 类 |
| 工具面 | read/write 14 · bash 6 · write 4 · read 3 · r+w+b 1 · r+b 1 | **只用 pi 7 个工具中的 3 个**（read/write/bash）；edit/find/grep/ls 零覆盖 |
| 检查器 | file_content_eq 31 · dir_entries_eq 19 · contains 13 · file_exists 12 · json_field_eq 11 · file_not_exists 9 · reported_file_value 4 · not_contains 1 | 全是**文件树断言**；无编译/测试/退出码/过程约束类验证 |
| 任务同质化 | 大量"改 JSON 一字段 / 读文件汇报 / 删文件保留 X"变体 | 信息熵低，本质是少量原型参数化 |

### 1.2 核心问题（三点）

1. **能力覆盖缺口**：error_recovery（失败→重试）、clarify（信息缺失→反问）是「模型×Harness 组合体」鲁棒性的关键，但 coding 域一条没有——注册的 `has_error_step` / `wrote_after_error` / `asked_clarification` / `no_blind_write` 检查器在 coding 域全部闲置。
2. **工具面盲区**：pi 真实工具面 7 个（bash/edit/find/grep/ls/read/write），评估只覆盖 3 个。harness 的工具注册、参数校验、错误处理在 edit/find/grep/ls 上零曝光。
3. **验证维度单一**：只看"文件最终长什么样"，不看"怎么做到的"（先读后写/失败重试/确认后删除）与"是否真的能用"（编译/测试/命令退出码）。对编码 agent，"文件内容对"远不如"改完 bug 且测试通过"有区分力。

> 推论（待实测验证）：简单文件任务上真实 LLM 容易全过 → 所有 agent 都 ≈1.0，Pass 率无法区分 harness；只有加入过程约束、失败注入、长链路、运行验证类任务，才可能出现中间分数。

---

## 2. pi 真实 LLM 评估实测（2026-08-23 回填）

> 运行：`python -m agent_eval --agent pi --mode llm --datasets coding --k 2`（串行 58 次调用，约 28 分钟）
> 数据：`results/pi_coding_llm.json`（`_meta.agent_type=pi-llm`，model=google/gemma-4-12b-qat）

### 2.1 整体指标（k=2，58 episodes，29 模板）

| 指标 | 值 | Wilson 95% CI |
|---|---|---|
| Pass@k（上限） | **0.8621** | — |
| Pass^k（可靠性） | **0.7586** | [0.6347, 0.8504] |
| Pass^k(strict) | **0.6552** | — |
| 首错用例数 | 6 | — |

### 2.2 by-capability 切片

| capability | n | pass^k | 解读 |
|---|---|---|---|
| confirm | 12 | **1.00** | 删除/保留类任务全部做对 → **无区分力** |
| tool_call | 52 | 0.73 | 有区分 |
| state_read | 36 | 0.67 | 有区分 |

### 2.3 per-template 三档分布（关键证据）

| 档 | 数量 | 模板 | 任务模式 |
|---|---|---|---|
| Pass^k=1.0 | **19** | 单文件写/读、删除保留类、多文件读汇报、rename、move_tree… | 简单文件操作 |
| Pass^k=0.5 | **6** | base_fs_edit_001 · hard_fs_refactor_001 · hard_fs_edit_then_verify_001 · hard_fs_rewrite_001 · mid_fs_edit_json_001 · mid_fs_edit_nested_001 | **全部是 read→write 全量重建** |
| Pass^k=0.0 | **4** | base_fs_write_002（嵌套路径）· hard_fs_pipeline_001 · mid_fs_transform_001（读算写）· mid_fs_branch_001（条件分支） | 嵌套目录 / 计算 / 分支决策 |

### 2.4 结论（验证 §1.2 推论 + 新发现）

1. **数据集已有区分度**：整体 Pass^k=0.76 落在 (0.4, 0.95)，29 模板呈三档分布——不再是 1.0/0.0 两极，**"评估不出性能"的第一层问题（天花板/地板）已被真实 LLM 模式解决**。
2. **失败高度集中在一个模式：read→write 全量重建**（6 个半过全是它，first_error_steps 集中在 write 步骤）。原因：数据集只暴露 read/write/bash 三个工具，模型 read 后必须全量重写文件 → 字段保不住 → pass_to_pass 失败。**这正是 harness 的 edit 工具（行级编辑）能解的**——工具面缺失把"模型重建准确性"误当成了任务难度。
3. **confirm 全过 → 现有删除类任务对 harness 无区分力**（gemma 对"必须保留"红线敏感），需要陷阱化。
4. **base_fs_write_002（src/main.py 嵌套路径）全挂**：暴露 write 工具对父目录的处理行为（是否自动建目录）——harness 行为盲区，值得专门设计验证。
5. **条件分支/读算写全挂**：区分的是模型计算/决策能力，与 harness 关系小——这类任务可保留但别当作 harness 指标。

> **一句话**：现在的区分度主要来自"模型能力"（gemma 的弱点），harness 的贡献仍被掩盖。要评估 harness 本身，下一步必须补**工具面（edit/search）**、**过程约束**、**失败恢复**、**陷阱化 confirm** 四类任务——即 §3 的扩充方向。

---

## 3. 扩充方案

### 3.1 扩充总原则

- **目标不是"更多同质任务"，而是"补全区分维度"**：每个新模板必须能回答"这测的是 harness 的哪个部件、哪种失败会在这暴露"。
- 沿用现有 Schema（TaskTemplate：capability[]/tier/difficulty/available_tools/verifier/must_not_do/leak_guard），不新造字段；缺能力时扩展 `capability` 枚举（如 `code_edit`/`search`/`run_verify`）。
- 三档递进仍按"步骤/工具数"，但 **difficulty 独立标记认知复杂度**（陷阱、多解、负反馈）。

### 3.2 六个扩充方向（按优先级，已按 §2 实测修订）

| # | 方向 | 补的能力/工具 | 示例任务 | 新增检查 | 实测依据 |
|---|---|---|---|---|---|
| 1 | **编辑工具面（新最高优先）** | pi 的 edit 工具（行级编辑） | "用 edit 精确改第 N 行，不用整体重写"；"把出现 3 次的 `timeout=10` 只改第 2 处" | 新增 `edit_minimal`（轨迹用 edit 且无冗余全量写） | §2.3：6 个半过全是 read→write 重建——edit 是 harness 侧解法，能把"模型重建准确性"与"harness 编辑能力"解耦 |
| 2 | **confirm 陷阱化** | 隐蔽红线、相似文件 | "删除 backup-1.tmp，但保留 backup1.tmp（名字相似）"；"删除 .tmp 时排除 keep.tmp" | 复用 `file_exists` 硬否决 + 新增 `no_blind_delete`（轨迹级） | §2.2：confirm 12/12 全过，现有任务太直白无区分力 |
| 3 | **error_recovery 域** | 失败→重试、瞬时错误 | "第一次写文件失败（瞬时），重试直到成功"；"命令 exit≠0 后读 stderr 修正再跑" | `has_error_step` + `wrote_after_error`（已注册，接线） | 能力 0 覆盖，且是 harness 鲁棒性核心 |
| 4 | **clarify 域** | 信息缺失→反问，不盲猜 | "删除哪个文件未指明（目录有多个候选）→ 必须反问确认" | `asked_clarification`（已注册，接线） | 能力 0 覆盖 |
| 5 | **搜索工具面** | find/grep/ls | "在嵌套目录里 grep 定位 TODO 再修改"；"find 出大于 1KB 的文件" | 新增 `used_tool`（轨迹级：必须调用指定工具） | pi 7 工具只测 3 个；搜索是编码 agent 主流程 |
| 6 | **运行验证 + 嵌套路径** | bash 验证 / mkdir+write | "修好 bug 后运行 `python script.py` 输出必须为 X"；"在 src/deep/ 下建文件（验证父目录行为）" | 新增 `cmd_exit_zero` / `cmd_output_contains`（运行态检查） | §2.3：base_fs_write_002 嵌套路径全挂，暴露 write 父目录行为盲区 |

### 3.3 规模与分层

- **总量目标**：coding 域 29 → **~60 模板**（新增 ~30，其中 edit 工具面 4~6、confirm 陷阱 4、error_recovery/clarify 各 4、搜索工具面 4~6、运行验证/嵌套路径 4~6、长链路过程约束 4）。
- 分层建议（新增部分）：base 补 error_recovery/clarify 各 2 + confirm 陷阱 2（1~2 步）；Middle 补 edit/搜索工具面 6~8（2~3 步）；hard 补运行验证/长链路/复杂陷阱 8~10（4+ 步，含陷阱）。
- **难度正交**：tier（结构复杂度：步骤/工具数）与 difficulty（认知难度：陷阱/负反馈/多解）分开标记，便于按需切片。
- **保留存量**：现有 29 条是"模型能力基线"（简单任务全过、重建类半过），扩充不动它们，只做增量——保证两次运行可比。

### 3.4 新增基础设施（框架侧小改）

1. **检查器**（`datasets/checks.py` CHECK_REGISTRY）新增：
   - `cmd_exit_zero` / `cmd_output_contains`：bash 执行命令并断言退出码/输出（在 FsEnv 内执行，注意 Windows 兼容：用 `cmd /c` 或 python 子进程）。
   - `used_tool` / `edit_minimal` / `step_order`：轨迹级检查（读 Trajectory 而非 final_state）——验证"怎么做的"。
2. **capability 枚举扩展**：`error_recovery`/`clarify` 已在 base 域存在（biz 用了），coding 域直接复用枚举即可；新增 `search`/`code_edit`/`run_verify` 三个枚举值，更新 `datasets/capabilities.py`。
3. **失败注入**：error_recovery 需要"第一次调用失败"——FsEnv 增加瞬时失败注入开关（对齐 `ToolCallingEnv._fail_first_call`），dataset 里用 `env: {"backend":"disk", "fail_first_call": true}` 表达。

### 3.5 防泄漏与质量控制（沿用红线）

- 每个新模板仍走 `wire_leak_guard`（canary + fresh_after + isolation），参数化生成器复用（int/email/name/choice）。
- **新增模板必须满足"双检可区分"**：写完后用 mock 完美执行者（`--agent mock`）验证 fail_to_pass 全过；再用一个故意错版验证会被捕获（回归防护）。
- 数据评审走既有核查罗盘：字段齐全、check fn 在注册表、available_tools 与 env 匹配、must_not_do 语义正确。

### 3.6 验收标准（区分"模型区分"与"harness 区分"）

**已达成（本次实测）**：整体 Pass^k=0.76 ∈ (0.4, 0.95)，29 模板三档分布（19/6/4），按 capability 切片有差异（confirm 1.0 vs tool_call 0.73 vs state_read 0.67）——§3.6 旧标准已满足。

**但注意**：当前区分度主要由"模型能力"驱动（gemma 的重建/计算弱点），不是 harness 性能。真正的 harness 区分需要满足以下**新标准（扩充后验收）**：

1. **工具面任务**：edit/搜索类任务上，模型表现应明显好于"只有 read/write"时的同构任务（证明 harness 工具可用性带来的增益可被测量）；或至少工具类任务的通过率与 read/write 类显著不同。
2. **过程约束触发**：error_recovery/clarify/陷阱 confirm 任务出现 `has_error_step`/`asked_clarification`/硬否决 归因（证明过程检查在起作用，能抓出"怎么做的"问题）。
3. **失败归因落到 harness 部件**：至少 1 类失败能归因到工具行为（如 write 父目录、edit 行定位、命令退出码）而非纯模型内容生成——这才算"评估出了 harness 性能"。

---

## 4. 执行清单

1. [x] LLM 评估结果回填 §2，验证/修正 §1.2 推论（**已回填**，2026-08-23）
2. [ ] 框架侧：checks.py 新增检查器（edit_minimal/used_tool/cmd_exit_zero/cmd_output_contains/no_blind_delete）+ capabilities 枚举扩展 + FsEnv 失败注入
3. [ ] 数据侧：新增 ~30 模板（按 §3.2 优先级、§3.3 分层），落 `datasets/data/coding/` 新文件或追加现有
4. [ ] 质量校验：mock 全过 + 错版可捕获 + 39 测试无回归
5. [ ] 重跑 pi LLM 评估，对照 §3.6 新验收标准（harness 区分）
