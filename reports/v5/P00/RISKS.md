# V5-P00 风险

- Evidence Tier: `DEVELOPMENT`
- Alpha Promotion Eligible: `false`

1. 两份 v4 源计划不存在，归档完整性只能标记为 `INSUFFICIENT_EVIDENCE`。
2. 历史报告缺乏统一元数据，只能通过 v5 sidecar 清单保守重置，不能反向伪造来源事实。
3. P06 fixture 的极短窗口和占位 hash 会制造荒谬的年化指标，必须永久禁止作为 Alpha 证据。
4. v5 Truth、Forecast、Causal 和 Forward 证据尚不存在；P00 通过也不等于策略有效。
5. 完整 CI 会重建部分历史开发工件；本轮已在 CI 尾部重新生成并校验迁移索引，该执行风险已关闭。
