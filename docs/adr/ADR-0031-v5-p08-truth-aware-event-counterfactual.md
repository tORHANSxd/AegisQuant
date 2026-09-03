# ADR-0031：V5-P08 Truth-aware Event Counterfactual

- 状态：Accepted
- Date: 2026-09-03
- Decision owners: AegisQuant research governance

## 背景

旧事件影响实现把委员会分数乘固定 horizon scale，只适合确定性 fixture，无法回答“没有事件时市场
本来会怎样”。P07 已提供完整概率预测与公平 OOS 竞技，但尚未隔离事件模态的增量。

## 决策

1. 每个事件预测 cell 必须同时产生同 asset、instrument、horizon、regime、模型、市场 tensor、
   calibration split、OOS 样本和资源预算的 Market-only 与 Event-conditioned 预测。
2. 事件条件快照内嵌并重验 CanonicalEvent 与 directional gate，显式导出 decision-time Truth、
   source quality、evidence independence/dependency、contradiction、manipulation、novelty、reflection、
   Surprise、entity/asset relationship 和 narrative lineage。
3. `EventIncrement` 由两侧完整概率预测逐字段重算，禁止调用方直接提交差值或跨 fold/revision 拼接。
4. 每个 horizon 的消融必须包含 Market-only、Event-only、Market+Event、Risk-only，以及 Truth、
   Event、Text、Timestamp、Asset 五类 permutation/placebo；所有臂使用相同 OOS lineage。
5. 事件增量门禁至少要求 Market+Event 超过 Market-only，且 Truth/Event/Text/Timestamp/Asset
   置换均按冻结阈值退化。任何失败只得到记录负结果，不得 Promotion。
6. Rumor、未确认、已 price-in 或反射质量不足的事件只能 risk overlay；directional forecast 必须
   abstain。LLM、事件层和 Dashboard 无下单能力。
7. 生产源码不再保存固定 `HORIZON_SCALE`。历史证据需要兼容时，scale 必须由测试/生成器显式注入，
   输出继续标记为非权威 `RESEARCH_PROPOSAL_ONLY`。
8. P08 不打开 Final Holdout，不下载外部大模型权重，不声称真实准确率、因果效应、Alpha 或收益。

## 后果

- 事件增量成为两侧反事实差分，而不是新闻强度乘常量。
- Truth 层、事件内容和时间/资产映射是否真正有用，可通过独立置换被否证。
- 契约更严格但仍保持模型无关；真实有效性留给后续公网 OOS 与 Forward 证据。
