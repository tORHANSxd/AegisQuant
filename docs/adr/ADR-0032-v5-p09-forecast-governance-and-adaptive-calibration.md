# ADR-0032：V5-P09 Forecast Governance 与自适应校准

- 状态：Accepted
- Date: 2026-09-03
- Decision owners: AegisQuant research governance

## 背景

P07/P08 已提供公平 OOS 预测、事件反事实与负结果保存，但尚未把模型分歧、OOD、动态权重、独立
质疑和滚动覆盖率合并为一个可重算的拒绝边界。现有静态 split conformal 与 drift helper 缺少完整
cell、时间窗和工件 lineage，Meta-Reasoner 也不得成为隐形交易员。

## 决策

1. Meta-Reasoner 与 Skeptic 只输出 `RESEARCH_RECOMMENDATION_ONLY`；两者都没有订单能力，任何
   建议只能收紧权重上限或增加 abstain 原因。
2. `ReasoningContext` 必须预先提交 Meta-Reasoner 与 Skeptic 各自不同的 prompt hash 和模型
   revision hash；输出必须与该绑定逐项一致。两条路径只共享内容寻址的上游事实上下文，不得读取
   Arbiter 最终输出；HIGH/CRITICAL finding 必须阻止新增风险。
3. Council disagreement 由成员 expected return 重算。方向冲突或区间超阈值显式产生
   `MODEL_DISAGREEMENT` 类拒绝原因，调用方不得自报低分歧覆盖结果。
4. 动态 stacking 的证据来源白名单只有 validation、calibration、forward；每次 proposal 至少包含
   validation 与 calibration，只有在 PIT forward 工件真实可用后才允许附加 forward，P09 不伪造
   尚不存在的 forward。Final Holdout 永远禁止；使用 capped simplex、可行性检查与 maximum-step
   smoothing，按 asset×horizon×regime 的 PIT snapshot 路由。
5. OOD、UNKNOWN regime、低数据质量、不确定 Truth、低可靠度、未来 proposal 或 cell/model splice
   均 fail closed。
6. 时间序列只允许 adaptive/distribution-aware conformal。distribution-aware 路径使用每条预测
   区间 half-width 归一化 nonconformity，并把校准出的 scale multiplier 应用于新预测自己的 base
   half-width；零 scale 拒绝。滚动窗口绑定 dataset、模型、校准、唯一样本、prediction time、
   outcome availability 和 decision time，不声明 exchangeability。
7. coverage shortfall、过度覆盖、样本不足与过期窗口必须生成 NONE/RECALIBRATE/DEGRADE/ABSTAIN
   动作；最终 Forecast governance 从原始工件重算所有拒绝原因。
8. P09 仍为 DEVELOPMENT，不打开 Final Holdout，不连接 execution，不声称真实准确率、Alpha 或收益。
   P10 负责把预测治理绑定到成本、组合和独立风险路径。

## 后果

- LLM 能帮助找矛盾和提出反事实，但不能替代统计 ensemble、成本或风险决策。
- 预测分歧、OOD 与校准漂移从“报表字段”变成可重算 abstain 条件。
- 当前哈希仍不是外部真实性证明，真实覆盖率与权重有效性必须由公网 OOS/Forward 数据验证。
