# Binance 一致性检查

- Kline vs trades：`PASS`
- Local book vs bookTicker：`PASS`
- 时间字段：event/available/ingest/processed/revision 均由严格模型约束。
- 不完整 Kline：保留 `close_time`，并标记 `INCOMPLETE_KLINE`，不静默当作收盘数据。
