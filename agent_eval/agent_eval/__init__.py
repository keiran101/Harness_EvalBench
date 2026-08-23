"""agent_eval —— Agent 评估框架（按《Agent 评估顶层设计方案》6 层重建）。

包内模块（实现时逐步补全）：
- core.py            : 数据模型（EvalCase / Step / Trajectory / VerificationResult / EvalReport）
- datasets/          : 数据集层（模板 / base 能力 / 验证器 / 防泄漏 / Registry）
- metrics/           : 指标层（Pass@k / Pass^k / 首个错误步）
- environments/      : 评估环境层（工具调用型 + 确定性验证器）
- judge/             : LLM-as-a-Judge 层（Dummy / LLM 结构）
- observability/     : 可观测性 + 漂移检测
- closure/           : 闭环（bad case → 回归集）
- evaluator.py       : 编排
"""
