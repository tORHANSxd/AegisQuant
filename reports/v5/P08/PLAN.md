# V5-P08 实施计划

## 目标

在 P07 Forecast Council 上实现可审计的 `MarketOnlyForecast`、`EventConditionedForecast`
与逐周期 `EventIncrement`，并用同一 OOS lineage 完成事件模态消融和置换检验。阶段只验证契约、
门禁和负结果保存，不使用 fixture 宣称真实事件 Alpha。

## 实施范围

1. 复用 P07 的 14 档 horizon、概率分布、校准工件、能力矩阵与 Market State Tensor。
2. 将 CanonicalEvent、TruthAssessment、NarrativeDiffusion、MarketReflection 和 directional gate
   绑定成内容寻址的 PIT 事件条件快照。
3. Market-only 与 Market+Event 每次只比较同一 asset、instrument、horizon、regime、模型、市场
   tensor、校准 split、训练/校准/测试样本和资源预算。
4. 逐 horizon 计算 Expected Return、全分位数、方向概率、Volatility、Tail、Liquidity、Spread、
   Slippage 和 Abstain 的差值。
5. OOS 消融必须包含 Market-only、Event-only、Market+Event、Risk-only，并执行 Truth、Event、
   Text、Timestamp 与 Asset permutation/placebo；不退化即 fail closed。
6. 移除生产源码中的固定 `HORIZON_SCALE`，旧报告生成只能显式注入 fixture scale，且永远保持
   `RESEARCH_PROPOSAL_ONLY`。
7. 新增版本化 Schema、确定性阶段证据、ADR、CI/Manifest/state 接线、攻击测试和完整验收材料。

## 验收门槛

- Market+Event vs Market-only 消融可复算且同折同样本；
- Truth permutation 与 Event/Text permutation 有显式结果；
- Timestamp/Asset placebo 有显式结果；
- EventIncrement 按 horizon 报告；
- 固定 `HORIZON_SCALE` 不再存在于生产候选代码；
- Final Holdout、Alpha Promotion、订单、真实账户和 Live trading 继续锁定；
- 完整 CI、独立复核、内容寻址 Manifest 全部通过后才授权 V5-P09。
