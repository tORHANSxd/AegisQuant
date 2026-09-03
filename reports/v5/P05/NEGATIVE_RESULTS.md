# V5-P05 负结果与禁止外推

- 全部事件值、TruthAssessment、叙事来源和市场指标均为确定性 `DEVELOPMENT` fixture。
- `MarketReflectionScore=0.40/0.90` 只是门禁正负控，不是市场已定价的真实概率估计。
- `0.80` 是 bootstrap threshold，不具备跨资产、跨事件、跨制度环境的稳定性证明。
- low price-in confirmed 场景仅证明研究候选可通过；不证明其方向、幅度、持续时间或净收益。
- high price-in、rumor、缺失指标和 legacy 无门禁路径均被阻断并归零；这是安全负控，不是模型
  准确率。
- narrative diffusion 的来源数量、速度和响应延迟没有在真实跨平台数据上校准。
- 未执行真实事件反应数据集、因果识别、placebo/pre-trend、OOS forecast 或交易成本后回测。
- 未产生 Alpha、Paper、Shadow、Testnet、Canary 或 Live Promotion 证据。
- Live trading、订单提交和真实账户连接保持关闭。
- 历史 Manifest 只有工作树内结构与哈希自洽，没有外部签名锚。

拿四组自编数字算出 `0.90`，再喊“市场已经定价 90%”，这不叫量化，叫给小数点穿西装。
P05 只证明未知会被关门、穿越会被抓住；真实有效性后续拿公开 PIT 数据说话。
