# V5-P01 — Truth Contract Foundations

- Evidence Tier: `DEVELOPMENT`
- Alpha Promotion Eligible: `false`
- Live Trading Locked: `true`

## 规格边界

本阶段严格对应 v5 SSOT 第 2039–2054 行，只实现 `AtomicClaim`、
`TruthAssessment`、`SourceIdentity` 可用时间、`EvidenceGraph` 契约和修订时间语义。
P02 来源可靠度、P03 检索、P04 Truth Council 与校准、P05 以后预测和交易能力均不提前
冒领。

## 实施顺序

1. 建立原子 Claim 类型、精确 span、原文、语言、实体和完整时间字段。
2. 将 FACT、FORWARD_FACT、QUOTE 与解释、观点、预测、传闻在进入 Truth 前硬分流。
3. 建立完整 TruthAssessment 概率字段、TruthState、理由、证据图 hash 和可用时间。
4. 扩展 EvidenceGraph 节点、边、独立来源计数、依赖分数和可复现 hash。
5. 建立版本链、修订、删除和评估的强类型 PIT 查询；所有查询满足
   `available_at <= decision_time`。
6. 生成 JSON Schema、确定性证据、单元测试、属性测试和完整 CI 结果。

## Acceptance

- 未来修订、未来删除和未来评估不能进入历史决策视图。
- 修订链缺口、前驱错误、时间倒退和来源集合错配全部 fail closed。
- OPINION、INTERPRETATION、PREDICTION、RUMOR 不能创建 TruthAssessment。
- 转载或同源材料不能增加独立证据数。
- AtomicClaim、TemporalRevision、TruthAssessment 和 EvidenceGraph hash 可复现。
- 完整 V5-P01 CI、最终工件清单和清单自检全部通过。
