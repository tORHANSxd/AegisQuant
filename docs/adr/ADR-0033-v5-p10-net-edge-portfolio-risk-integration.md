# ADR-0033：V5-P10 Net Edge、Portfolio 与 Risk 强绑定

- 状态：Accepted
- Date: 2026-09-03
- Decision owners: AegisQuant research governance

## 背景

P08/P09 已能给出事件增量与受治理的预测，但预测仍未成为组合提案和独立风险裁决的强制上游。
仅凭 `predicted_return > 0` 做决策会忽略成本分布、已价格反映、数据质量和尾部置信边界；把 rumor
直接翻译成方向订单更是典型的“新闻一响，风控白养”。

## 决策

1. 唯一顺序为 `Forecast → Truth Gate → Price-In Gate → Cost → Net Edge → Portfolio → Risk`。
   `IntegratedDecisionReport` 从嵌套工件重算结果，调用方不得自报通过状态。
2. `ExecutionCostModelV2` 同时覆盖 Backtest/Paper/Live，固定包含 fee、spread、slippage、
   market impact、queue probability、maker adverse selection、latency、funding、borrow、settlement
   和 liquidation risk。`REPLAY_QUEUE` 必须绑定 L2 snapshot/delta、trade、order arrival、
   cancel/replace 与 queue-ahead 六类输入。
3. Forecast 与 Cost 必须共享 asset×instrument×horizon×sleeve×decision-time 以及同一组带概率
   scenario；`queue_probability` 作为成交概率折算可实现 gross edge，再扣除其余成本。Net Edge 的
   均值、正收益概率、置信下界与 edge/cost ratio 全部重算，scenario 数量上限为 4096。
4. 成本 TCA 失准通过 `cost_confidence` 乘法折减 `P(net_edge > 0)`；置信度和 TCA 工件也进入
   成本模型内容哈希。P11 再以连续 Forward 的 predicted-vs-realized TCA 替换 DEVELOPMENT fixture。
5. Gate 阈值由 `NetEdgePolicy` 按 asset×horizon×sleeve 版本化。`0.60` 只存在于 Bootstrap
   fixture，不是代码默认值；OOS 阈值必须绑定独立证据哈希。
6. 组合腿的 `SignalId` 必须从 ForecastDistribution 内容哈希确定性派生；风险裁决必须精确绑定
   proposal id/hash、有效期，以及 asset、instrument、strategy、account、current/proposed target
   都一致的同方向 approved target。任一缺失均输出内容寻址的 `NO_TRADE`。
7. `EventRiskOverlay` 与 `EventDirectionalAlpha` 是互斥类型。中等 Truth + 极高 Severity 只能在
   独立风险裁决为 REDUCE_ONLY/HALTED 时产生保护性 overlay；Directional Alpha 必须同时通过
   Truth、Novelty、Price-In、Event Increment、Net Edge、Portfolio 和 Risk。
8. 全部 P10 输出仍是 DEVELOPMENT research proposal；没有 execution import、OrderIntent 或
   SubmitOrderCommand，Final Holdout、订单提交和 Live trading 继续锁定。

## 后果

- 正期望预测不再能绕过成本；新闻候选不再能绕过组合或独立风险。
- abstain 从隐含的零权重升级为可审计、可哈希的 `NO_TRADE` 结果。
- 内容哈希证明工作区内的完整性和交叉绑定，不证明外部预测或 TCA 的真实性；真实公网 OOS 与
  Forward 证据仍须在 P11/P12 和最终公开数据回测中取得。
