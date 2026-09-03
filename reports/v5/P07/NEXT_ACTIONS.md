# V5-P07 后续动作

P07 验收后，`V5-P08` 才可开始。P08 必须：

1. 构造同一 split、同一 market state、同一校准政策下的 `MarketOnlyForecast`、
   `EventConditionedForecast` 与 `EventIncrement`。
2. 事件模型输入 Truth probability、source quality、独立证据、dependency、novelty、reflection、
   actual-vs-expected Surprise、event/entity/asset relationship、regime、microstructure 与 cross-asset state。
3. 执行 Market+Event vs Market-only、truth permutation、event permutation 消融，并按 horizon 报告增量。
4. 禁止固定 `HORIZON_SCALE`；允许 Truth 上升但预期影响近零，也允许中等 Truth 伴随高 tail risk。
5. 继续使用 PIT、purge/embargo、独立 calibration、冻结 Final Holdout 与等折 OOS 约束。
6. 保留无增量、成本后为负、calibration 变差、OOD/abstain 和模型失败结果。
7. 继续保持 zero-shot/Champion 不等于 Promotion、订单关闭、真实账户不连接与 Live 锁定。
