# AegisQuant v5.0 — Truth-Verified Event Intelligence + Causal AI Forecasting + Robust Alpha
## Codex 统一修改总任务书

> **文档性质：** AegisQuant v4.0 与 v4.1 的统一替代版本 / Codex 单一事实来源（SSOT）  
> **目标：** 将 AegisQuant 从“功能完整的量化研发平台”迭代为“能够严格验证真实 Alpha、验证新闻事实、估计事件增量影响、输出校准概率，并在没有优势时主动不交易”的个人加密资产量化系统。  
> **规格日期：** 2026-09-02  
> **默认内部时间：** UTC  
> **默认用户展示时区：** Asia/Tokyo，可配置  
> **首要交易场所：** Binance；架构保留 OKX / Bybit / Deribit 扩展能力  
> **实盘原则：** 本计划不得自动解除 `LIVE_TRADING=false` / `ORDER_SUBMISSION_ENABLED=false`  
> **核心原则：** 新闻真实性 ≠ 新闻方向性；预测准确 ≠ 可交易；可交易 ≠ 值得下单；任何 LLM 永远不能直接下单。  

---

# 0. 给 Codex 的最高优先级执行契约

## 0.1 本文件替代关系

本文件替代并吸收：

- `AegisQuant_v4.0_Robust_Alpha_Live_Readiness_Codex_Master_Plan.md`
- `AegisQuant_v4.1_AI_Forecasting_KLine_Intelligence_Upgrade.md`

如旧计划与本文件冲突，以本文件为准。

不得删除旧文档；将其移动到：

```text
docs/archive/plans/
```

并在根目录新增：

```text
AegisQuant_v5.0_Truth_Causal_AI_Forecast_Codex_Master_Plan.md
```

## 0.2 第一原则

本项目不以“模型越大越好”“AI 判断越自信越好”“Sharpe 越高越好”为目标。

最终目标是：

```text
真实、可追溯、Point-in-Time 数据
        ↓
事实真实性概率
        ↓
事件结构化理解
        ↓
市场反事实预测
vs
事件条件预测
        ↓
事件增量 / 因果影响估计
        ↓
多模型 Forecast Council
        ↓
概率校准 + 不确定性
        ↓
真实交易成本
        ↓
Net Edge Distribution
        ↓
Portfolio
        ↓
Independent Risk Engine
        ↓
TRADE / REDUCE / NO_TRADE
```

系统必须允许最终结论为：

```text
NO_PROVEN_ALPHA
NO_TRADE
INSUFFICIENT_EVIDENCE
TRUTH_UNCERTAIN
EVENT_ALREADY_PRICED
MODEL_DISAGREEMENT
OOD
```

这些不是失败，而是正确输出。

## 0.3 明确禁止

Codex 禁止：

1. 让一个 LLM 直接读取一篇新闻后输出“真/假 + 涨/跌”。
2. 把 LLM 自报的 `95% confidence` 当作统计校准概率。
3. 把“官方账号真实发布”误当成“发布内容必然真实”。
4. 把转载数量当独立证据数量。
5. 把标题 sentiment 当作事件交易 Alpha。
6. 使用固定 `HORIZON_SCALE` 将新闻分数直接映射为未来收益。
7. 用未来修订后的新闻文本回测首次发布时间。
8. 使用未来才知道的新闻发布时间、文章更新时间、删除状态、互动数据。
9. 允许 Final Holdout 被反复查看。
10. 用 fixture / golden test / synthetic sample 作为真实 Alpha 证明。
11. 让新闻 Agent、Forecast Meta-Reasoner、Web Dashboard 持有下单密钥。
12. 因新闻“很重要”而绕过组合、成本或风险引擎。
13. 在证据不足时强制产生交易。
14. 将 C2PA/数字签名验证成功等价为事实内容正确。
15. 将模型 Forecast Loss 更低自动等价为更高实盘收益。

---

# 1. v5.0 必须首先修复的当前问题

## 1.1 `intelligence/impact.py` 的固定收益映射必须退出生产候选路径

当前类似：

```python
HORIZON_SCALE = {
    FIVE_MINUTES: ...,
    THIRTY_MINUTES: ...,
    FOUR_HOURS: ...,
    ONE_DAY: ...,
    SEVEN_DAYS: ...,
}
```

这种“事件强度 × 固定时间尺度常量 = 未来收益”的方法只能作为单元测试 fixture，不得继续作为事件 Alpha。

必须：

- 删除其 production candidate 身份；
- 保留 compatibility adapter 仅用于旧 artifact replay；
- 新建真实历史学习路径；
- 所有事件未来收益必须来自 point-in-time event-response dataset + 模型；
- 若没有真实历史证据，输出 `NO_EVENT_ALPHA_MODEL`。

## 1.2 Fixture / Development / Real Evidence 必须硬隔离

建立：

```text
EvidenceTier:
- FIXTURE
- SYNTHETIC
- DEVELOPMENT
- OOS_DEVELOPMENT
- FINAL_HOLDOUT
- PAPER_FORWARD
- SHADOW_FORWARD
- TESTNET_FORWARD
- CANARY_LIVE
- LIVE
```

任何 Dashboard、报告、Promotion Gate 必须显示证据等级。

以下禁止作为 Alpha Promotion Evidence：

- FIXTURE
- SYNTHETIC
- golden test
- 5 秒 / 极短 CI backtest
- 占位 hash
- 人工构造收益
- 静态 scoreboard fixture

## 1.3 所有模型结果必须绑定真实 Trial Ledger

每个实验必须记录：

```text
run_id
parent_run_id
hypothesis_id
dataset_hash
universe_hash
feature_hash
label_hash
event_corpus_hash
source_registry_hash
truth_model_hash
split_hash
cost_model_hash
model_hash
parameter_hash
code_commit
container_digest
seed
started_at
finished_at
metrics
promotion_decision
failure_reason
```

任何缺字段的实验不得进入 DSR / PBO / multiple-testing 计算。

---

# 2. News Truth Engine：新闻真实性系统

新建：

```text
src/aegisquant/truth/
```

建议目录：

```text
truth/
├── contracts.py
├── source_registry.py
├── identity.py
├── provenance.py
├── claims.py
├── retrieval.py
├── evidence_graph.py
├── independence.py
├── contradiction.py
├── temporal.py
├── scoring.py
├── calibration.py
├── state_machine.py
├── manipulation.py
├── c2pa.py
└── audit.py
```

---

# 3. Truth Engine 必须拆分的概率

不得只有：

```text
truth_score
```

至少拆成：

```text
P(source_identity_authentic)
P(content_integrity_valid)
P(claim_true)
P(claim_current)
P(evidence_independent)
P(manipulated)
P(revision_risk)
P(source_compromised)
```

最终：

```text
TruthAssessment
```

至少包含：

```python
claim_id
source_document_ids
source_identity_probability
content_integrity_probability
claim_truth_probability
claim_current_probability
independent_evidence_count
evidence_dependency_score
contradiction_probability
manipulation_probability
revision_probability
calibration_bucket
truth_state
reason_codes
evidence_graph_hash
available_at
```

---

# 4. Source Identity 与来源真实性

## 4.1 Source Registry

建立版本化：

```text
SourceRegistry
```

来源必须包含：

```text
source_id
canonical_name
source_type
official_domains
official_social_accounts
public_keys
known_api_endpoints
jurisdiction
topic_domains
license_policy
historical_accuracy
historical_correction_rate
historical_retraction_rate
first_report_latency
compromise_incidents
valid_from
valid_to
```

禁止仅凭域名字符串做 official 判断。

## 4.2 来源级别只是 Prior，不是 Verdict

初始化可以有：

```text
S: primary official / regulator / court / exchange / project official
A: high-quality wire / direct reporting
B: mainstream verified outlet
C: specialist media
D: social/KOL/channel
E: anonymous/unverified
```

但最终可靠度必须随：

```text
event_type × topic × geography × language × time
```

动态更新。

例如：

```text
source_reliability(source, event_type)
```

而不是一个永久静态分数。

---

# 5. C2PA / Content Credentials / Cryptographic Provenance

实现 C2PA Content Credentials 验证 adapter。

截至本规格日期，目标兼容最新稳定 2.x 系列，优先支持 C2PA 2.3。

必须支持：

- manifest presence
- signature validation
- trust-list validation
- timestamp validation
- ingredient / edit chain
- content hash binding
- generator information
- AI-generated / AI-modified assertions（如存在）
- certificate expiry / legacy trust model
- tamper detection

重要：

```text
C2PA_VALID
```

只能说明：

> provenance assertions 与资产绑定且通过验证。

不能说明：

> 图片、视频、文字描述中的事实一定真实。

因此：

```text
content_integrity_probability
```

和：

```text
claim_truth_probability
```

必须保持独立。

没有 C2PA 也不得自动判假。

---

# 6. Claim Decomposition：把新闻拆成原子事实

新建：

```text
AtomicClaim
```

必须把：

> “SEC 批准某 ETF，下周开始交易，这将大幅利好 BTC”

拆成至少：

```text
C1: SEC 批准某 ETF
C2: 下周开始交易
C3: 对 BTC 利好
```

分类：

```text
FACT
FORWARD_FACT
INTERPRETATION
OPINION
PREDICTION
QUOTE
RUMOR
```

Truth Engine 只直接裁决：

```text
FACT
FORWARD_FACT
QUOTE_AUTHENTICITY
```

`INTERPRETATION / OPINION / PREDICTION` 进入 Impact / Forecast 层。

必须保存 claim span、原文、语言、翻译、实体、时间、来源。

---

# 7. Evidence Retrieval：支持证据与反证必须同时检索

每个 Claim 必须建立：

```text
EvidenceSearchPlan
```

至少包含两个方向：

```text
support_queries
contradiction_queries
```

以及：

```text
primary_source_queries
official_denial_queries
revision_queries
timeline_queries
```

不能只找支持材料。

建议逻辑 Agent 分工：

```text
Evidence Agent
Primary Source Agent
Skeptic Agent
Timeline Agent
Manipulation Agent
Arbiter
```

注意：

Agent 只是检索/结构化/解释层。

最终概率不得由 Agent 投票比例直接得到。

---

# 8. Evidence Provenance Graph：解决“伪多源确认”

新建图结构：

```text
EvidenceGraph
```

节点：

```text
Claim
Source
Document
Author
Account
Organization
Quote
Attachment
MediaAsset
Event
```

边：

```text
PUBLISHED_BY
QUOTES
COPIES
CITES
DERIVED_FROM
REPOSTS
SAME_ORIGIN
CONTRADICTS
SUPPORTS
REVISES
DELETES
```

## 8.1 Independent Evidence

建立：

```text
EvidenceIndependenceModel
```

系统必须识别：

- 新闻社 syndicated content；
- 多篇文章引用同一匿名人士；
- 多账号转发同一原帖；
- 同一组织不同子品牌；
- 同一个新闻稿的机器改写；
- 同一媒体集团转载；
- 同一链上错误数据源被多人引用。

最终：

```text
article_count != independent_evidence_count
```

必须输出：

```text
evidence_dependency_score ∈ [0,1]
```

高依赖时不得因为“来源数量很多”提高真实性。

---

# 9. Temporal Truth：新闻历史版本必须可回放

所有内容必须至少记录：

```text
event_time
published_time
first_seen_time
available_time
ingested_time
updated_time
deleted_time
```

所有修订必须 append-only：

```text
revision_id
previous_revision_id
content_hash
observed_at
effective_at
diff
```

回测时只能看到：

```text
available_at <= decision_time
```

严禁：

- 12:00 的修订内容出现在 10:00 回测；
- 用最终互动量代替当时互动量；
- 用后来出现的 community note / fact check 回填过去；
- 用被删除后的状态判断当时真实性。

---

# 10. Truth Scoring：不要让 LLM 自己报概率

## 10.1 两阶段架构

### Stage A — Evidence Feature Extraction

LLM/规则生成结构化特征：

```text
primary_source_present
official_signature_valid
source_reliability_prior
independent_source_count
dependency_score
contradiction_count
official_denial_present
temporal_consistency
entity_consistency
quote_consistency
media_provenance
revision_count
retraction_history
language_translation_confidence
manipulation_signals
```

### Stage B — Calibrated Truth Model

必须使用训练/校准数据学习：

```text
P(claim_true | evidence features)
```

候选：

- Logistic regression baseline
- Gradient boosting
- Bayesian hierarchical model
- calibrated ensemble

优先可解释、可校准。

LLM 自报 confidence 只能作为一个弱特征，不能作为最终概率。

## 10.2 Calibration

至少：

```text
Brier Score
Log Loss
ECE
MCE
Reliability Diagram
Calibration slope
Calibration intercept
```

要求：

预测为 0.9 的历史 claims，最终应约有 90% 被确认。

---

# 11. Truth State Machine

状态：

```text
UNVERIFIED
RUMOR
PARTIALLY_CORROBORATED
VERIFIED_PRIMARY
VERIFIED_MULTI_SOURCE
CONTRADICTED
RETRACTED
STALE
UNKNOWN
```

只允许状态按证据时间前进/修订。

状态不是永久不可逆：

```text
VERIFIED → RETRACTED
VERIFIED → CONTRADICTED
```

必须支持。

---

# 12. Manipulation / Compromised Source Defense

新增检测：

- account compromise
- domain spoofing
- Unicode homograph
- fake screenshots
- impersonation
- deleted/reposted manipulation
- coordinated posting
- bot burst
- unusual propagation graph
- source behavior drift
- paid-promotion patterns
- forged PDF / image metadata
- altered media
- prompt injection in external content

如果官方账号被盗：

```text
source_identity_authentic = high
claim_truth = low/unknown
source_compromised = high
```

这是必须支持的情况。

---

# 13. Event Understanding：事实与观点完全分离

新建：

```text
CanonicalEvent
```

字段至少：

```text
event_id
event_type
entities
assets
jurisdiction
actual_value
expected_value
whisper_value
surprise_value
event_stage
truth_assessment_id
novelty
severity
persistence
transmission_channels
affected_assets
source_ids
first_seen_at
confirmed_at
available_at
```

---

# 14. Actual vs Expected：市场交易的是 Surprise

对于宏观/监管/财报/ETF 等事件：

必须支持：

```text
Actual
Consensus
Whisper
Prior Probability
```

并产生：

```text
Surprise = Actual - Expected
```

或离散版本：

```text
MORE_POSITIVE_THAN_EXPECTED
AS_EXPECTED
MORE_NEGATIVE_THAN_EXPECTED
```

禁止：

```text
“降息 = 利好”
“ETF 批准 = 一定涨”
“黑客攻击 = 一定跌”
```

必须结合预期。

---

# 15. Market Reflection / Price-In Engine

建立：

```text
MarketReflectionScore
```

输入至少：

- event rumor first-seen time
- pre-confirmation price move
- abnormal return
- volume spike
- OI change
- funding change
- basis
- options IV/skew（如有）
- cross-asset response
- search/social diffusion
- liquidation flow
- market depth

输出：

```text
P(already_priced)
MarketReflectionScore
```

高 `MarketReflectionScore` 时：

- directional trade 权重下降；
- 可转为风险 overlay；
- 可研究 sell-the-news，但必须单独验证；
- 不得简单继续追方向。

---

# 16. Event Diffusion / Narrative Graph

建立：

```text
NarrativeDiffusionGraph
```

跟踪：

```text
first_source
first_verified_source
传播速度
独立来源增长速度
KOL扩散
新闻社扩散
不同语言圈扩散
交易量响应延迟
价格响应延迟
```

目标不是“社交热度越高越涨”。

目标是估计：

```text
信息扩散处于哪个阶段？
市场是否已经完成吸收？
```

---

# 17. Event Impact：必须使用反事实

这是 v5.0 的核心。

不得直接预测：

```text
P(up | event)
```

至少同时建立：

```text
MarketOnlyForecast
EventConditionedForecast
```

例如：

```text
P(up | market state) = 0.52
P(up | market state + event) = 0.66
```

定义：

```text
EventIncrement = 0.14
```

同样对收益分布：

```text
DeltaExpectedReturn
DeltaVolatility
DeltaTailRisk
DeltaLiquidity
```

---

# 18. Causal Event Study / Synthetic Control

建立：

```text
src/aegisquant/research/causal/
```

建议：

```text
causal/
├── contracts.py
├── matching.py
├── synthetic_control.py
├── event_study.py
├── uplift.py
├── diagnostics.py
└── placebo.py
```

对重大事件研究，不能只使用：

```text
future_return after event
```

必须估计：

> 如果没有这个事件，在相同市场状态下资产本来可能怎么走？

候选：

1. synthetic control
2. matched historical states
3. doubly robust / uplift estimation
4. causal forest（数据足够时）
5. short-horizon event study
6. placebo tests

注意：

长 horizon / 高波动 / 事件时点与市场状态相关时，传统线性 factor event study 容易偏误。

因此：

- 4h 以上重大事件优先 synthetic-control / matched controls；
- 必须做 placebo；
- 必须报告 pre-treatment fit；
- pre-trend 不合格则不宣称 causal effect。

---

# 19. Event Response Dataset

构建：

```text
EventResponseDataset
```

每个事件必须 PIT。

字段：

```text
event_id
event_type
asset
truth_probability_at_t
source_quality_at_t
novelty_at_t
market_reflection_at_t
actual
expected
surprise
regime
pre_event_returns
pre_event_vol
spread
depth
funding
basis
oi
liquidations
cross_asset_state
narrative_state
return_5m
return_30m
return_4h
return_1d
return_7d
vol_delta
liquidity_delta
tail_event
mfe
mae
```

所有 label 必须严格在未来。

---

# 20. Truth-aware Event Forecast Model

预测不能只输入“event sentiment”。

至少输入：

```text
truth_probability
source_quality
independent_evidence_count
dependency_score
novelty
market_reflection
actual-vs-expected surprise
event type
entity / asset relationship
regime
market microstructure
derivatives state
cross-asset state
```

模型必须允许：

```text
truth_probability ↑
但
expected market impact ≈ 0
```

也必须允许：

```text
truth_probability 中等
但
tail risk 非常高
```

---

# 21. Rumor 与 Confirmed Event 必须使用不同策略

## Rumor

默认：

```text
directional alpha = disabled
```

可作用于：

```text
risk reduction
leverage reduction
liquidity protection
maker withdrawal
new-risk pause
```

## Confirmed

只有同时满足：

```text
Truth Gate
+
Novelty Gate
+
Not-Priced Gate
+
Forecast Gate
+
Net Edge Gate
```

才可进入 directional candidate。

---

# 22. Forecast Council：K线 + 市场状态 + 事件联合

保留 v4.1 的 Forecast Council，但升级为 truth-aware。

输入：

```text
MarketStateTensor
TruthStateTensor
EventStateTensor
```

模型议会至少支持：

## Time-Series Foundation Models

- TimesFM 2.5
- Chronos-2
- Moirai-2
- Toto 2.0

所有都只是 candidate。

## Crypto-specific supervised

- PatchTST
- iTransformer
- TFT
- N-HiTS
- N-BEATSx
- TiDE
- TCN
- DLinear / NLinear
- multi-scale Patch Transformer
- state-space / Mamba candidate（许可和依赖允许时）

## Microstructure

- DeepLOB-style
- LOB Transformer
- Order Flow Transformer
- Hawkes process
- neural residual for Hawkes

## Vision

严格 PIT：

- ViT
- Swin
- chart + volume + heatmap

必须做：

```text
Numeric-only
Vision-only
Numeric+Vision
```

无 OOS 增量则淘汰 Vision。

---

# 23. Forecast 目标必须从“下一根 K 线”升级

每个 horizon 输出：

```text
return distribution
q01/q05/q10/q25/q50/q75/q90/q95/q99
P(up)
P(flat)
P(down)
realized volatility distribution
future high-low range
MFE
MAE
barrier hit probabilities
tail-risk probability
liquidity forecast
spread forecast
slippage forecast
epistemic uncertainty
aleatoric uncertainty
abstain probability
```

时间尺度：

```text
5s
15s
30s
1m
3m
5m
15m
30m
1h
4h
12h
1d
3d
7d
```

不是每个资产都必须支持全部 horizon。

---

# 24. Market Regime Router

状态至少：

```text
TREND
MEAN_REVERSION
LOW_VOL_COMPRESSION
VOL_EXPANSION
LIQUIDITY_CRISIS
NEWS_SHOCK
LIQUIDATION_CASCADE
FUNDING_DISLOCATION
CORRELATION_BREAKDOWN
RISK_ON
RISK_OFF
UNKNOWN
OOD
```

Council 权重：

```text
w(model | asset, horizon, regime, data_quality, calibration, truth_state)
```

权重只能根据：

```text
validation
calibration
forward
```

更新。

Final Holdout 不得训练权重。

---

# 25. High-Reasoning AI 的正确用途：Meta-Reasoner

高推理 LLM 输入：

```text
truth assessments
evidence graph
event structure
model forecasts
market regime
model reliability
calibration
OOD
news/event evidence
market reflection
cost forecast
portfolio state
risk state
```

任务：

1. 发现模型矛盾；
2. 解释信息源冲突；
3. 检查事件是否与市场状态一致；
4. 检查新闻是否已经 price-in；
5. 提出反事实；
6. 判断模型可能错在哪里；
7. 生成 skeptic questions；
8. 推荐模型 mixture constraints；
9. 推荐 abstain；
10. 输出可审计 explanation。

禁止：

```text
LLM output → order
```

必须：

```text
LLM output
→ structured recommendation
→ deterministic/statistically learned ensemble
→ cost
→ portfolio
→ risk
```

---

# 26. Skeptic / Red-Team 必须是独立路径

每个高置信事件/预测必须回答：

```text
如果新闻是假的，最可能哪里有问题？
如果新闻是真的但价格不按预期走，为什么？
是否已被市场提前交易？
是不是同源转载？
是否发生 source compromise？
是否存在 opposite positioning？
是否存在 liquidity trap？
是否为 regime shift？
是否 OOD？
是否只有 BTC beta 而非事件 alpha？
```

Skeptic 不能共享 Arbiter 的最终 prompt 输出。

---

# 27. Probabilistic Ensemble

禁止固定平均。

比较：

- Bayesian model averaging
- constrained stacking
- online stacking
- regime-conditioned stacking
- dynamic mixture of experts
- quantile ensemble
- conformalized ensemble

必须限制：

- 权重非未来；
- 权重训练不接触 Final Holdout；
- 单一新模型不能立即取得大权重；
- forward degradation 自动降权。

---

# 28. Calibration：真实性与走势都要校准

## 28.1 Truth Calibration

按：

```text
source class
event type
language
claim type
```

维护。

## 28.2 Forecast Calibration

按：

```text
asset × horizon × regime
```

维护。

## 28.3 方法

必须比较：

- isotonic
- Platt / logistic calibration
- temperature scaling
- beta calibration
- adaptive conformal inference
- distribution-aware conformal
- rolling quantile calibration

时间序列不得机械使用要求 exchangeability 的普通静态 conformal。

必须检测：

```text
coverage drift
interval undercoverage
calibration drift
```

---

# 29. 自动 Reliability Decay

## 29.1 新闻源

如果 source：

```text
historical correction/retraction ↑
false claim rate ↑
```

则自动：

```text
reliability ↓
```

## 29.2 Truth Model

如果：

```text
predicted 90% claims
actual confirmed rate falls materially below 90%
```

自动：

```text
truth model state:
NORMAL
→ DEGRADED
→ RESTRICTED
→ RETIRED
```

## 29.3 Forecast Model

如果：

```text
calibration worsens
net edge disappears
cost underestimation rises
```

则：

```text
weight ↓
```

严重：

```text
RETIRED
```

---

# 30. Unified Net Edge

所有方向性预测最终必须进入：

```text
ForecastDistribution
+
ExecutionCostDistribution
=
NetEdgeDistribution
```

交易 Gate 不再使用：

```text
predicted_return > 0
```

而使用至少：

```text
E(net_edge) > 0
P(net_edge > 0) >= threshold
lower_confidence_bound > economic_floor
expected_edge / expected_cost >= ratio
truth_state acceptable
market_reflection acceptable
uncertainty acceptable
OOD acceptable
data_quality acceptable
portfolio allows
risk allows
```

阈值必须版本化并通过研究确定。

---

# 31. 初始保守 Gate

以下数值只是 **Bootstrap 风险门槛**，不是声明为最优参数。

必须允许未来通过 OOS 数据调整。

## 31.1 News Directional Candidate 初始门槛

建议：

```text
claim_truth_probability >= 0.99
contradiction_probability <= 0.05
manipulation_probability <= 0.05
```

独立证据：

```text
官方 primary source：
可允许 independent_evidence_count = 1
但必须 identity/integrity 高可信

非 primary：
建议 independent_evidence_count >= 2
且 evidence_dependency_score 低
```

## 31.2 Price-In

```text
MarketReflectionScore >= 0.80
```

默认不追 directional news trade。

## 31.3 Forecast

初始建议：

```text
P(net_edge > 0) >= 0.60
```

真正阈值必须按：

```text
asset × horizon × sleeve
```

OOS 决定。

不得把 0.60 永久硬编码成 Alpha 真理。

---

# 32. Risk Overlay 与 Directional Alpha 分离

建立：

```text
EventRiskOverlay
EventDirectionalAlpha
```

## EventRiskOverlay

允许：

```text
Truth 中等
+
Severity 极高
```

采取：

- 减仓
- 减杠杆
- 暂停新增风险
- 撤 maker
- 提高 liquidity buffer

## EventDirectionalAlpha

必须：

```text
Truth 极高
+
Novelty
+
Not priced
+
Event Increment
+
Net Edge
```

全部通过。

---

# 33. Execution Reality 必须统一

当前 Backtest / Portfolio / Live 成本定义必须使用同一：

```text
ExecutionCostModelV2
```

至少：

```text
fee
spread
slippage
market_impact
queue_probability
maker_adverse_selection
latency_cost
funding
borrow
settlement
liquidation_risk
```

## 33.1 Maker Queue

至少两种：

```text
CONSERVATIVE_QUEUE
REPLAY_QUEUE
```

REPLAY_QUEUE 输入：

```text
L2 snapshots / deltas
trades
order arrival time
cancel/replace
queue ahead
```

## 33.2 Live TCA

持续比较：

```text
predicted_cost
vs
realized_cost
```

成本模型失准时：

```text
NetEdge confidence ↓
```

---

# 34. Alpha Research Protocol

## 34.1 Split

必须：

- walk-forward
- purge
- embargo
- rolling/expanding
- regime robustness
- CPCV / CSCV where appropriate

## 34.2 Anti-overfit

必须：

- PBO
- PSR
- DSR
- FDR
- Reality Check / SPA
- block bootstrap
- parameter plateau
- cross-asset robustness
- cross-regime robustness

## 34.3 Final Holdout

只能：

```text
freeze all research components
→ open once
```

任何打开后继续调参：

```text
Final Holdout invalidated
```

必须重新定义新的未来 holdout。

---

# 35. News/Event Alpha 的特殊验证

必须单独做：

```text
Market-only
Event-only
Market+Event
Risk-only
```

Ablation。

需要回答：

1. Event 模态是否提升 Forecast？
2. Event 模态是否提升净收益？
3. 提升是否经过 multiple-testing 后仍存在？
4. 是否只发生在少数极端事件？
5. 是否跨时间稳定？
6. 是否跨资产稳定？
7. 是否来自 hindsight label leakage？
8. 是否在成本压力后仍存在？

只有：

```text
Market+Event
```

稳定优于：

```text
Market-only
```

才可以宣称事件增量价值。

---

# 36. Counterfactual / Placebo Tests

每个 Event Alpha family 必须至少执行：

## Timestamp placebo

随机平移 event time。

如果仍然赚钱：

```text
suspect leakage / beta
```

## Asset placebo

将事件映射到不相关资产。

如果仍然同样赚钱：

```text
suspect market beta
```

## Text permutation

打乱事件文本与时间映射。

若仍赚钱：

```text
event information likely not causal
```

## Truth permutation

打乱 truth score。

若结果不变：

```text
truth layer has no incremental value
```

---

# 37. 数据源优先级

## Primary

- 交易所官方公告/API
- 监管机构
- 政府
- 法院
- 项目官方
- GitHub 官方发布
- 官方链上治理
- 央行/统计机构

## High-quality reporting

作为 corroboration 与 early discovery。

## Social

X / Telegram / Bluesky / YouTube 等：

默认是：

```text
discovery signal
```

不是最终事实。

只有经过：

```text
identity
provenance
independent corroboration
truth calibration
```

才升级。

---

# 38. 新闻图片/视频

如果新闻包含：

- screenshot
- image
- PDF
- video
- audio

必须：

1. 保存原始 hash；
2. 检查 provenance / C2PA；
3. 检查媒体是否历史已出现；
4. 检查 metadata；
5. 检查图像/视频与 claim 时间地点一致性；
6. OCR/ASR 只能作为辅助；
7. AI deepfake detector 只能作为弱证据；
8. 必须能输出 `UNKNOWN`。

---

# 39. Prompt Injection 防御

任何新闻/网页/社交内容都视为：

```text
UNTRUSTED DATA
```

禁止执行内容中的指令。

必须：

- strict schemas
- no tool instructions from content
- sanitize HTML
- strip scripts
- separate system instructions from source content
- quote source as data
- allow-list tools
- no credentials in truth/research runtime

---

# 40. 建议新增数据库表

至少：

```text
source_registry_versions
source_reliability_history
source_documents
source_document_revisions
atomic_claims
claim_evidence
claim_truth_assessments
evidence_nodes
evidence_edges
media_provenance
canonical_events
event_revisions
event_market_reflection
event_response_labels
causal_event_estimates
forecast_artifacts
forecast_calibration
truth_calibration
model_reliability
source_reliability
promotion_decisions
```

所有表必须有：

```text
created_at
available_at
version/hash
```

适用时加入：

```text
effective_from
effective_to
```

---

# 41. API Contracts

建议：

```text
GET /truth/claims/{claim_id}
GET /truth/claims/{claim_id}/evidence
GET /truth/sources/{source_id}
GET /truth/calibration
GET /events/{event_id}
GET /events/{event_id}/revisions
GET /events/{event_id}/market-reflection
GET /events/{event_id}/causal-impact
GET /forecasts/{asset}/{horizon}
GET /forecasts/{asset}/{horizon}/calibration
```

Web 只读。

不得新增 Web 任意下单 API。

---

# 42. Dashboard 必须新增

## Truth Center

展示：

```text
Claim
Truth probability
Source identity
Independent evidence
Contradictions
Manipulation risk
Revision history
Evidence graph
```

## Event Radar

展示：

```text
Event
Truth
Novelty
Price-in
Expected surprise
Affected assets
Narrative diffusion
```

## Forecast Council

展示：

```text
Model predictions
Model weights
Regime
Disagreement
Calibration
OOD
```

## Event Increment

展示：

```text
Market-only
Event-conditioned
Difference
```

## Net Edge

展示：

```text
Gross forecast
Cost forecast
Net edge
P(net > 0)
No-trade reason
```

---

# 43. Codex 阶段计划

---

## V5-P00 — Evidence Reset & SSOT Migration

目标：

- 将 v5 设为 SSOT；
- archive v4.0/v4.1；
- 扫描 fixture / synthetic / placeholder hash；
- 建立 EvidenceTier；
- Dashboard 禁止把 fixture 当真实收益。

必须产出：

```text
reports/v5/P00/PLAN.md
reports/v5/P00/FIXTURE_AUDIT.json
reports/v5/P00/EVIDENCE_TIER_MIGRATION.json
reports/v5/P00/ACCEPTANCE.md
```

Acceptance：

- 所有历史报告都有 evidence tier；
- fixture 与 real research 硬隔离；
- live lock 不变。

---

## V5-P01 — Truth Contracts & Temporal Semantics

实现：

- AtomicClaim
- TruthAssessment
- SourceIdentity
- EvidenceGraph contracts
- temporal revision semantics

Acceptance：

- future revision impossible in PIT query；
- property tests；
- hash reproducibility；
- claim vs opinion separation tests。

---

## V5-P02 — Source Registry + Identity + C2PA

实现：

- source registry
- official identity rules
- C2PA 2.x / 2.3-compatible verifier
- content integrity
- source compromise state

Acceptance：

- spoof domain tests
- signature tests
- invalid C2PA tests
- no-C2PA != false
- C2PA-valid != claim-true

---

## V5-P03 — Evidence Retrieval + Independence Graph

实现：

- support + contradiction retrieval contracts
- provenance graph
- syndication/copy detection
- evidence dependency scoring

Acceptance：

构造：

```text
10 articles from 1 original rumor
```

系统必须：

```text
independent_evidence_count ≈ 1
```

而不是 10。

---

## V5-P04 — Truth Council + Calibration

实现：

- evidence feature extraction
- baseline truth model
- boosting/bayesian candidate
- calibration
- truth state machine
- reliability decay

Acceptance：

- Brier / LogLoss / reliability diagrams；
- calibration split 独立；
- LLM confidence 不是最终概率；
- historical revision replay。

---

## V5-P05 — Event Canonicalization + Surprise + Price-In

实现：

- CanonicalEvent
- actual/expected/whisper
- surprise
- MarketReflectionScore
- narrative diffusion

Acceptance：

- 已 price-in 的 confirmed event 不得默认生成 directional signal；
- rumor 与 confirmed 分开；
- all fields PIT。

---

## V5-P06 — Event Response Dataset + Causal Layer

实现：

- EventResponseDataset
- matched states
- synthetic control
- placebo tests
- causal diagnostics

Acceptance：

- pre-treatment fit report；
- event timestamp placebo；
- asset placebo；
- permutation tests；
- causal claim only if diagnostics pass。

---

## V5-P07 — Forecast Council 2.0

实现：

- TimesFM
- Chronos
- Moirai
- Toto
- supervised experts
- microstructure
- optional vision
- MarketStateTensor

Acceptance：

- equal OOS folds；
- capability matrix；
- zero-shot ≠ promotion；
- model arena；
- no single universal model assumption。

---

## V5-P08 — Truth-aware Event Forecast & Counterfactual

实现：

```text
MarketOnlyForecast
EventConditionedForecast
EventIncrement
```

Acceptance：

- Market+Event vs Market-only ablation；
- truth permutation；
- event permutation；
- event increment reported by horizon；
- no fixed HORIZON_SCALE。

---

## V5-P09 — Meta-Reasoner + Skeptic + Ensemble + Conformal

实现：

- Meta-Reasoner
- independent Skeptic
- dynamic stacking
- regime router
- adaptive/distribution-aware calibration

Acceptance：

- LLM cannot order；
- disagreement handling；
- OOD abstention；
- calibration drift action；
- interval coverage monitoring。

---

## V5-P10 — Net Edge + Portfolio + Risk Integration

实现：

```text
Forecast
→ Truth Gate
→ Price-In Gate
→ Cost
→ Net Edge
→ Portfolio
→ Risk
```

Acceptance：

- news cannot bypass cost；
- news cannot bypass risk；
- `NO_TRADE` first-class；
- risk overlay separate from directional alpha。

---

## V5-P11 — Paper / Shadow Forward Proof

最低要求：

- continuous forward data
- no future corrections
- predicted vs realized truth calibration
- predicted vs realized forecast calibration
- predicted vs realized cost
- event increment attribution
- incident logs
- restart/recovery

不得使用回测替代 Forward。

建议最低：

```text
Paper ≥ 30 calendar days
```

且必须有足够独立事件样本。

如果事件样本不足：

```text
extend paper
```

而不是降低门槛。

---

## V5-P12 — Testnet / Canary Readiness

必须先解决原有：

- real Binance Testnet evidence
- external alert delivery
- soak / forward validation
- reconciliation

只有：

```text
Truth calibration PASS
Forecast calibration PASS
Cost calibration PASS
Paper PASS
Shadow PASS
Testnet PASS
Risk PASS
```

才能生成：

```text
CANARY_REVIEW_READY
```

仍不得自动解锁 live。

---

# 44. Promotion Gate

候选策略必须同时通过：

## Data

- PIT
- no leakage
- historical universe
- source revisions
- real hashes

## Truth

- calibrated
- source-independent evidence
- contradiction aware
- revision aware

## Forecast

- calibrated
- stable
- OOD aware
- uncertainty reported

## Economics

- net positive
- cost stressed
- capacity stressed
- latency stressed

## Statistics

- DSR
- PBO
- FDR
- SPA/Reality Check
- bootstrap
- parameter stability

## Forward

- Paper
- Shadow
- Testnet

## Risk

- drawdown
- margin
- liquidity
- venue
- security
- event risk
- reconciliation

任意 hard gate 不通过：

```text
NO_PROMOTION
```

---

# 45. 真实性准确率的目标定义

不要设置：

```text
“新闻判断正确率必须 99%”
```

这种单一指标。

原因：

- 类别不平衡；
- 官方消息与匿名 rumor 难度不同；
- 假阳性与假阴性成本不同。

必须报告：

```text
precision
recall
specificity
F1
PR-AUC
Brier
LogLoss
ECE
```

并单独统计：

```text
high-confidence bucket accuracy
```

例如：

```text
P_true >= 0.99
```

的 claims，如果实际无法接近其名义概率，必须禁止用于 directional alpha。

---

# 46. 走势准确率的目标定义

同样禁止：

```text
方向准确率 > 55% 就上线
```

必须综合：

```text
direction calibration
CRPS
pinball loss
Brier
net return
Sharpe
drawdown
turnover
cost ratio
capacity
tail loss
```

最终经济目标：

```text
expected value after all costs
```

---

# 47. 回撤优先

即使预测很强：

```text
P(win) = 0.65
```

仍有连续失败可能。

因此仓位必须来自：

```text
forecast uncertainty
truth uncertainty
event uncertainty
portfolio covariance
liquidity
cost
drawdown state
```

而不是：

```text
confidence × max leverage
```

禁止 full Kelly。

最多研究 fractional Kelly candidate，且必须有硬上限。

---

# 48. 模型与来源的 Champion/Challenger

## Model Champion

按：

```text
asset × horizon × regime
```

选。

## Source Reliability Champion

按：

```text
event type × domain
```

动态。

## Truth Model Champion

与 Challenger shadow 比较。

任何 Champion 都可：

```text
DEGRADED
RETIRED
```

---

# 49. Failure Injection

必须测试：

- 假官方域名
- 官方账号被盗
- 10 个同源转载
- 官方后续撤稿
- 新闻先 rumor 后 confirmation
- 新闻 timestamp 延迟
- API 重复事件
- 新闻删除
- 文章正文修改
- 假图片
- C2PA invalid
- C2PA valid but false caption
- prompt injection
- stale market data
- L2 gap
- model disagreement
- event already priced
- exchange outage
- unknown order state

系统必须 fail closed。

---

# 50. 性能要求

Truth/News pipeline 不应阻塞市场数据主循环。

架构：

```text
Market hot path
```

和：

```text
Intelligence async path
```

隔离。

事件信号必须带：

```text
valid_until
```

过期不执行。

Latency 必须加入事件 Alpha 回测：

```text
source publish
→ discover
→ retrieve
→ verify
→ reason
→ forecast
→ risk
→ order
```

新闻 Alpha 的真实优势必须扣掉整条 latency。

---

# 51. 参考技术原则

Codex 在实施时优先参考：

1. C2PA / Content Credentials 2.x（当前优先兼容 2.3）用于媒体 provenance；
2. 模块化事实核验：claim decomposition → retrieval → evidence synthesis → contradiction → calibrated verdict；
3. 时间序列 adaptive / distribution-aware conformal，而非机械静态 conformal；
4. 高波动/长窗口事件研究优先 synthetic-control / matched counterfactual；
5. TimesFM / Chronos / Moirai / Toto 等必须经公平 OOS arena，不默认信任 Foundation Model；
6. 新闻事件永远要求 Market-only counterfactual baseline。

---

# 52. Codex 修改当前代码的明确清单

重点审计并修改：

```text
src/aegisquant/intelligence/impact.py
src/aegisquant/intelligence/committee.py
src/aegisquant/intelligence/pipeline.py
src/aegisquant/intelligence/graph.py
src/aegisquant/intelligence/world/*
src/aegisquant/features/events.py
src/aegisquant/research/baselines.py
src/aegisquant/research/models/*
src/aegisquant/research/validation/*
src/aegisquant/backtest/*
src/aegisquant/portfolio/*
src/aegisquant/risk/*
src/aegisquant/runtime/*
src/aegisquant/readmodels/*
apps/web/*
```

新增：

```text
src/aegisquant/truth/*
src/aegisquant/research/causal/*
src/aegisquant/research/forecasting/*
```

不得为了 v5 重写已经正确的：

- accounting ledger
- idempotent execution
- independent risk lock
- PIT base primitives
- live lock
- reconciliation

除非测试证明现有实现与新契约冲突。

---

# 53. 每个 V5 Phase 的强制产物

```text
reports/v5/Pxx/
├── PLAN.md
├── SUMMARY.md
├── TEST_RESULTS.json
├── ACCEPTANCE.md
├── RISKS.md
├── NEGATIVE_RESULTS.md
├── NEXT_ACTIONS.md
├── ARTIFACT_MANIFEST.json
└── ADR_REFERENCES.md
```

新增全局：

```text
state/V5_PROJECT_STATE.yaml
state/TRUTH_MODEL_STATE.yaml
state/FORECAST_MODEL_STATE.yaml
state/SOURCE_RELIABILITY_STATE.yaml
state/V5_OPEN_RISKS.yaml
```

---

# 54. Codex 第一轮只执行 V5-P00

Codex 收到本文件后：

1. 完整读取本文件；
2. 读取当前 repo；
3. 生成 gap analysis；
4. 不安装全部大模型；
5. 不连接真实账户；
6. 不请求 production API key；
7. 不解除 live lock；
8. 执行 V5-P00；
9. 运行完整 CI；
10. 生成 V5-P00 acceptance evidence；
11. 未通过不得进入 V5-P01。

---

# 55. 最终定义：什么叫“最好”

AegisQuant v5.0 不追求：

> 每次新闻都猜对。

也不追求：

> 每根 K 线都预测对。

而追求：

```text
知道证据有多可靠
+
知道预测有多不确定
+
知道信息是否已被定价
+
知道事件相对无事件世界增加了多少预测能力
+
知道扣除真实成本后是否还有优势
+
知道什么时候不应该交易
```

最终可靠交易逻辑应接近：

```text
Truth Probability
×
Event Novelty
×
Event Increment
×
Forecast Calibration
×
Execution Realism
×
Portfolio Diversification
×
Risk Discipline
```

而不是：

```text
LLM Confidence
×
Leverage
```

系统允许：

```text
99% 的事实置信度
但
NO_TRADE
```

因为消息可能已经 price-in。

也允许：

```text
60% 的事实置信度
+
高尾部严重性
→
RISK REDUCTION
```

但不做方向性赌博。

---

# 56. 最终成功标准

只有当系统能长期证明：

```text
真实新闻校准有效
事件增量预测有效
K线/市场预测校准有效
交易成本预测有效
严格 OOS 后仍有净 Edge
Forward Paper 后仍存在
Shadow 后仍存在
Testnet 执行无重大偏差
风险控制可证明有效
```

才有资格进入极小规模 Canary Review。

任何阶段如果得出：

```text
NO_PROVEN_ALPHA
```

Codex 必须保留该结论，不得为了“完成项目”人为放宽统计门槛。

这就是本项目最重要的工程纪律。
