# Harness_EvalBench

<p align="center">
  <b>给 agent harness 做"验收测试"的开源评估框架</b><br>
  <sub>用真实的编码任务，测出 PI / OpenCode / DeepSeek 到底谁把活干成了——而不是谁说得好听</sub>
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.8+-blue">
  <img alt="Zero dependencies" src="https://img.shields.io/badge/Dependencies-0-brightgreen">
  <img alt="Local model" src="https://img.shields.io/badge/Model-gemma--4--12b--qat-orange">
</p>

> 这套框架评的是 **harness——agent 的执行外壳**，而不是模型本身。把 PI / OpenCode / DeepSeek(dsh) 三套 agent 摆上同一张考卷，用本地部署的 `google/gemma-4-12b-qat` 作为统一的"考生大脑"去驱动它们：**模型一致，唯一变量就剩 harness 的工程实现**。最后框架不再看 agent 说了什么，而是检查任务结束后的**真实环境状态**，判定谁真的交付了正确结果。
>
> 仓库把评估框架（`agent_eval/`）、harness 真实输入捕获（`context_capture/`）、数据集与分析报告归拢在一处，一条命令即可复现整场擂台赛。

## 为什么需要它

每天都要和 coding agent 打交道——Cursor、Claude Code、OpenCode，还有本项目同场对比的 PI / OpenCode / DeepSeek(dsh)，都在说"我更会写代码"。可当一个 agent 面对一个真实的、带文件系统的编码任务时，**它到底是真把活干成了，还是只是看起来在干活？** 体感靠不住，这个判断只能交给评估。

我们想把这个模糊的"行不行"，变成一个可复现、可比较的数字。三件事是这套框架的初心：

1. **不考嘴皮子，考交付物。** 我们不直接比谁的解释更漂亮，而是看它**最终有没有把环境改对**——文件写没写、状态变没变、危险操作有没有先确认。这相当于把软件工程的"验收测试"思路搬到了 agent 上。
2. **戳破"分数高 = 可靠"的错觉。** 只看 `Pass@k`（跑 k 次至少一次成功）会轻易把一个"十次里九次翻车、一次蒙对"的 flaky 系统误判为可上线。`Pass^k`（连续 k 次都成功）才真正暴露可靠性——这是贯穿整个项目的一条元认知。
3. **掀开 harness 的盖子。** 三套 harness 跑同一个任务，system prompt 的措辞、工具 schema、上下文的拼装方式天差地别，这些"看不见的工程"恰恰是能力差异的隐藏来源。`context_capture/` 用反向代理把每一次真实请求逐字留底，让比较建立在证据上，而不是宣传上。

## 谁会感兴趣

- **想亲手跑一场"agent 擂台赛"的玩家**：框架**零外部依赖**（纯标准库），`python examples/run_demo.py` 一条命令就能看完整评估跑通，不需要任何 API key。
- **本地小模型也能玩**：评估对象是一个 12B 级的本地量化模型端点（`google/gemma-4-12b-qat`），你完全可以在自己的机器上把三套 harness 拉起来，比较它们在同一批任务上的真实表现。
- **想扩展评估的人**：数据集、指标、验证器都是**可插拔、可扩展**的——加自己的任务类型、换更大的模型、接你正在做的 agent，都只需实现少量接口。

## 目录结构

| 目录 | 作用 |
|---|---|
| `agent_eval/` | **核心**：6 层 agent 评估框架（零外部依赖），含 CLI、数据集、指标、环境、Judge、外部集成桥 |
| `context_capture/` | 用统一 LLM 反向代理，在真实执行中**逐字捕获**三套 harness 喂给 LLM 的输入 context |
| `agent_eval/data/` | 评测任务数据集（base / biz / coding / retrieval / keycases），与框架代码分离、版本可控 |
| `docs/` | 设计文档（`context_capture_design.md`、`superpowers/` 规格） |
| `papers/` | 参考论文（AI Agents in Depth 第六章原文） |
| `reports/` | 分析与对比报告（本地独立 git 仓库，不随主仓同步） |
| `results/` | 评估与捕获产物 JSON（自动生成，已 gitignore） |
| `scripts/` | 辅助脚本：`capture_proxy.py`、各类结果分析脚本、`run_retrieval_eval.sh` 等 |

## 快速开始

```bash
# 1) 跑一次完整的真实评估（PI + 本地 LLM，coding 数据集，k=2）
cd agent_eval
python -m agent_eval --agent pi --mode llm --datasets coding --k 2

# 2) 捕获三套 harness 在单个任务上的真实输入 context
bash context_capture/run_single_task.sh fs_write_001
```

## ⚠️ 本地 LLM 端点硬约束

> [!IMPORTANT]
> 评估所用 LLM 是本地部署、**性能有限**，所有调用必须**严格串行，严禁并发**。端点通过环境变量 `LLM_EVAL_BASE_URL` 配置，不要对本地端点做并行压测。
>
> 端点 `n_ctx=4096`，超长 context 会被截断——这直接决定了"工具面裁剪是技术妥协而非语义限定"的策略（见 `agent_eval` 文档）。

## 评估口径（关键纪律）

- 评估单元是 **Task / 轨迹（episode）**，验证**最终环境状态**而非文本对错（不是 QA）。
- 工具是 harness 的一部分，默认**不限定工具面**（满血评估）；`verifier` 只查最终状态 + 过程硬约束（confirm/clarify）。
- 跨 `agent_type` / `dataset_scope` / `k` / `mode` 的 `Pass@k`、`Pass^k` **不可直接比较**，须看输出文件里的 `_meta`。
- 详见 [`agent_eval/README.md`](agent_eval/README.md) 与 [`docs/`](docs/)。
