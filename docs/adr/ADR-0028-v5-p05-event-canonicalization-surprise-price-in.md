# ADR-0028：V5-P05 事件标准化、Surprise 与 Price-In 门禁

- 状态：Accepted
- 日期：2026-09-03
- 决策范围：CanonicalEvent、Event Surprise、Narrative Diffusion、Market Reflection、Directional Gate

## 背景

事实为真不等于市场尚未定价，市场已经波动也不等于事件必然为真。若把 rumor、官方确认、
actual/consensus、价格反应和方向预测揉成一个分数，系统既无法按决策时点回放，也会把后来
确认的信息倒灌到过去。旧事件影响路径还允许调用方直接传入一个粗粒度
`market_already_moved_score`，这个字段既没有输入快照，也没有完整性和新鲜度证明，不能继续
作为方向许可依据。

## 决策

1. `CanonicalEvent` 绑定原始 `EventCluster`、P04 `TruthAssessment`、事件值快照、Surprise、
   narrative diffusion 和 market reflection。事件身份与每个 revision 均内容寻址；后续 revision
   必须引用前序 revision，时间严格前进，并按显式状态迁移表禁止 confirmed 回退为 rumor。
2. 事件阶段从 `TruthAssessment.truth_state` 推导，而不是把来源的 `verified_source` 布尔值当作
   事实确认。官方肯定、官方否认和 rumor 保持不同语义；未来才可见的内容不能改变过去聚类。
3. actual、consensus/expected 和 whisper 分别使用带来源哈希、观察时间和可用时间的
   `TimedEventValue`。`EventSurprise` 只从同一 PIT snapshot 重算：数值事件为
   `actual - consensus`，并单独保留 `actual - whisper`；调用方不能注入独立 surprise 标量。
4. Narrative Diffusion 保存首次来源、首次已验证来源、独立来源/平台/语言/KOL/news-wire 数量、
   传播速度及价格/成交量响应延迟。所有响应都必须同时提供发生时间、可用时间与来源哈希。
5. `MarketReflectionScore` 使用十个必需市场维度和版本化权重。任何缺失或过期指标都会令
   score 为空、质量降级并 fail closed。默认 `0.80` 阈值仅是 `DEVELOPMENT` bootstrap policy；
   加权分数不是经过真实标签校准的“已定价概率”。
6. `EventDirectionalGate` 只允许 confirmed、反射数据完整且低于阈值的事件成为
   `RESEARCH_PROPOSAL_ONLY` 候选。rumor 只允许风险覆盖层；高 price-in 或数据不足必须阻断
   方向候选。所有门禁均固定 `order_submission_allowed=false`。
7. 旧 `EventImpactForecast` 与 world fusion 调用签名暂时保留兼容入口，但缺少
   `CanonicalEvent + EventDirectionalGate` 时强制 abstain 并把方向收益归零。影响预测契约因此
   升级到 `2.0.0`，标记 `MIGRATION_REQUIRED`，历史 v1 schema 继续保留。

## 后果

- P05 能确定性重放“rumor → confirmed → 是否已定价”的上下文，但不识别因果效应。
- 低 price-in 只说明可以进入后续研究，不代表事件能赚钱，也不会开启订单路径。
- 所有证据仍为 `DEVELOPMENT`；真实 PIT 事件/市场数据、校准和 OOS 效果留给 P06 及后续阶段。

## 回退条件

真实 PIT 标签若否定当前指标、权重或阈值，只能通过新 policy version 和新 ADR 替换；不得重写
历史 event revision、反填后见之明，或为兼容旧调用而恢复无门禁的非零方向输出。
