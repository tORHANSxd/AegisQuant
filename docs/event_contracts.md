# 事件契约与兼容性

## 信封

所有版本化事件使用 `EventEnvelope`：

```json
{
  "schema_name": "aegisquant.market-event",
  "schema_version": "1.0.0",
  "event_id": "event-id",
  "occurred_at": "2026-08-31T08:00:00Z",
  "available_at": "2026-08-31T08:00:01Z",
  "payload": {}
}
```

`schema_name` 和 semantic version 共同选择契约。`event_id` 表达经济事实身份；同一
事实重放沿用原 ID 和幂等键。

## 序列化

- 使用 UTF-8、排序键、紧凑分隔符和末尾 LF 的 canonical JSON。
- Decimal 作为十进制字符串写入，禁止转成二进制 float。
- NaN 和 Infinity 不能进入 JSON。
- 内容哈希为 canonical bytes 的 SHA-256。
- `serialize_event()` 与 `deserialize_event()` 必须保持经济字段、Decimal scale、
  强类型 ID 和 schema version。

## Schema Registry

V5-P05 新增 `TimedEventValue`、`EventValueSnapshot`、`EventSurprise`、
`NarrativeDiffusionObservation`、`NarrativeDiffusionSnapshot`、
`TimedMarketReflectionMetric`、`MarketReflectionPolicy`、`MarketReflectionScore`、
`CanonicalEvent` 与 `EventDirectionalGate` 的 `1.0.0` 契约，compatibility=`NONE`。
事件值、传播和市场反射输入都绑定来源哈希与 PIT 时间；缺失/过期市场指标 fail closed，rumor
与高 price-in 事件不得成为方向候选。低 price-in confirmed 事件也仅可进入
`RESEARCH_PROPOSAL_ONLY`，不能下单。`EventImpactForecast` 因新增 canonical event revision 与
directional gate 绑定升级为 `2.0.0`、compatibility=`MIGRATION_REQUIRED`；旧 v1 schema 保留，
但无门禁的旧调用只能 abstain 并输出零方向影响。

`schemas/events/registry.json` 固化 schema 名称、版本、Python model、相对路径、
兼容模式和文件 SHA-256。`scripts/generate_schemas.py --check` 验证生成结果没有漂移。
每份 schema 使用 JSON Schema Draft 2020-12，并由契约测试调用 metaschema 校验。

## 迁移规则

`SchemaMigrationRegistry` 注册 `schema_name + from_version -> to_version` 的显式纯函数。
迁移必须：

1. 不修改调用者提供的原 payload；
2. 逐版本推进，不允许环；
3. 找不到完整路径时失败，不猜测默认字段；
4. 迁移后由目标 Pydantic model 重新严格验证；
5. 旧原始事件和旧 schema 保持不可变。

V5-P01 新增 `AtomicClaim`、`TruthAssessment`、`EvidenceGraph` 和
`TemporalRevision` 的 `1.0.0` 契约。`SourceIdentity` 因新增必需的 PIT
`available_time`，显式升级为 `2.0.0` 且标记 `MIGRATION_REQUIRED`；旧
`source-identity-v1.json` 保留为历史 schema。v1 迁移只能把 `first_observed_time` 作为
最早可辩护的 `available_time`，不得从后来的身份状态反填历史。兼容测试继续使用受控
legacy fixture 验证迁移机制，没有捏造一个可供生产消费的旧版本。

V5-P02 新增 `SourceRegistryDocument`、`OfficialIdentityObservation`、
`OfficialIdentityAssessment`、`DetachedSignatureVerification`、`C2paVerificationResult`、
`ContentIntegrityAssessment`、`ContentAuthenticityBinding` 与 `SourceCompromiseEvent` 的
`1.0.0` 契约，compatibility=`NONE`。这些对象分别承载 registry prior、身份、密码学
provenance、内容完整性和来源攻陷状态；它们不得合并成一个粗糙的 `verified` 布尔值，
也不得推导 claim truth。

V5-P03 新增 `EvidenceSearchPlan` 与 `EvidenceRetrievalHit` 的 `1.0.0` 契约，
compatibility=`NONE`。搜索计划必须同时包含 support、contradiction、primary source、
official denial、revision 与 timeline 六类查询，并在 decision time 前可用。检索命中绑定
具体 document/revision、query hash、PIT 时间、rights、lineage 和官方身份状态；Agent 只负责
检索与结构化，概率聚合固定不得采用 Agent 投票比例。`EvidenceGraph` 增加可选内容 hash 与
共同 origin 指纹，独立性指标按内容、origin、所有权及 provenance 连通分量计算。

V5-P04 新增 `EvidenceFeatureVector`、`TruthCalibrationSample`、`TruthCalibrationMetrics`、
`TruthCouncilReport`、`TruthStateTransition`、`SourceReliabilitySnapshot` 与
`TruthModelReliabilitySnapshot` 的 `1.0.0` 契约，compatibility=`NONE`。训练、验证、校准与
测试分区必须按时间隔离，同一 claim 不得跨分区重复；`EvidenceFeatureVector` 绑定带
lineage hash 与可用时间的 `EvidenceFeatureInputSnapshot`，retrieval hit 绑定图中的 revision、
source identity 和 content hash。LLM confidence 仅保留为审计字段，不进入最终概率模型。
Truth 状态和来源/模型可靠度使用 hash-linked、PIT 可回放历史，允许
`VERIFIED → RETRACTED`，但禁止未来修订、未来 outcome 或标签回填过去。

V5-P06 新增事件响应与因果研究契约。`EventResponseRow`、`EventResponseDataset`、
`HistoricalState` 与 `DoublyRobustObservation` 注册为 data contract；匹配、event study、
synthetic control、诊断 policy、pre-fit/pre-trend/balance/overlap、placebo、point estimate 与
`CausalEffectEstimate` 注册为 versioned event/config contract。事件 revision 与 `CanonicalEvent`
受约束绑定，所有特征和 nuisance prediction 必须在 decision time 前可见，所有 outcome 必须在
decision time 后产生并在 dataset `as_of_time` 前可知。诊断报告保存原始输入并重算结果；只有完整
诊断与合格 EvidenceTier 同时成立才允许因果表述。P06 的 `DEVELOPMENT` 证据不满足该条件，且
Alpha Promotion、订单与 Live trading 始终关闭。

V5-P07 新增 Forecast Council 2.0 契约。`MarketStateTensor` 与 `OosFoldEvaluation` 注册为 data
contract；`ModelCapability`、`CapabilityMatrix`、`ModelArenaSpec`、`CalibrationArtifact`、
`ForecastEnvelope`、`CandidateGateDecision`、`ModelArenaReport` 与 `VisionAblationReport` 注册为
versioned event/config contract，版本均为 `1.0.0`、compatibility=`NONE`。市场张量强制
observed/available/decision time 的 PIT 顺序和内容哈希；预测绑定能力、dataset、校准 artifact；竞技场
强制同 dataset、同 calibration、同 split、同时间和同样本身份，并禁止 prediction artifact 复用。
Catalog membership、zero-shot 或研究 Champion 均不等于 Promotion，订单与 Live trading 保持关闭。

V5-P08 新增 Truth-aware 事件反事实契约。`EventConditionSnapshot`、`MarketOnlyForecast`、
`EventConditionedForecast`、`EventIncrement` 与 `EventForecastAblationReport` 注册为 event contract；
`ForecastInputBinding`、`EventForecastComparisonLineage`、`EventAblationSpec` 与
`EventAblationEvaluation` 注册为 data contract，版本均为 `1.0.0`、compatibility=`NONE`。
Market-only 与 Market+Event 必须绑定同一市场张量、模型、校准、split、样本与资源预算；事件输入绑定
decision-time Truth、来源质量、证据独立/依赖、Surprise、Narrative、Price-In 与资产关系。事件增量
逐 horizon 重算，Truth/Event/Text/Timestamp/Asset 置换任一不退化即关闭门禁。旧
`EventImpactForecast` 的 horizon 系数改为调用方显式提供并内容寻址，契约升级至 `3.0.0`；生产源码
不再持有固定 horizon scale。P08 fixture 明确保留 Truth permutation 未退化的负结果，不能 Promotion。

V5-P09 新增 Forecast governance 契约。`MetaReasonerRecommendation`、
`IndependentSkepticAssessment`、`RegimeRoutingDecision`、`AdaptiveConformalReport` 与
`ForecastGovernanceReport` 注册为 event contract；`ReasoningContext`、`StatisticalWeightProposal`
与 `IntervalCoverageWindow` 注册为 data contract；`DynamicStackingPolicy` 与
`AdaptiveConformalPolicy` 注册为 config contract，版本均为 `1.0.0`、compatibility=`NONE`。
Meta-Reasoner/Skeptic 的 prompt/model revision 由上下文预提交，且只能输出结构化研究建议；统计权重
证据白名单只有 validation/calibration/forward，每次至少要求 validation/calibration，forward 只在
真实 PIT 工件可用后附加，禁止 Final Holdout。distribution-aware conformal 用预测区间 scale 归一化
nonconformity。Council 分歧、OOD、未知 regime、低质量/可靠度、coverage drift、样本不足与窗口过期
均由边界重算并可触发 abstain。P09 不连接订单，Promotion 与 Live trading 保持关闭。
