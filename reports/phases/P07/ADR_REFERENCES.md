# P07 ADR 引用

- `ADR-0001-runtime-and-version-policy.md`：生产 Python 3.13、候选 Python 3.14 与锁文件优先策略。
- `ADR-0003-live-lock.md`：`LIVE_TRADING` 锁与真实账户隔离。
- `ADR-0005-p02-columnar-data-foundation.md`：point-in-time 数据、可用时间和内容寻址基础。
- `ADR-0008-p04-multivenue-event-contracts.md`：事件证据、revision 与互动快照边界。
- `ADR-0009-p05-accounting-policy.md`：权威账本与净经济口径。
- `ADR-0010-deferred-acceptance-sequencing.md`：实现验证完成但正式验收延期，不生成
  `ACCEPTANCE.md`。
- `ADR-0011-p06-backtest-engine-policy.md`：历史规则、成本、撮合和权威回测边界。
- `ADR-0012-p07-feature-validation-baseline-policy.md`：P07 Feature/Label、时间验证、PBO/PSR/DSR、
  holdout、经典基线、scikit-learn/NumPy 与 AI-Trader 许可证边界。

本阶段没有新增 waiver；P03 的 24 小时公开流豁免仍由 ADR-0007 单独记录，不扩展为其他安全
或正确性门禁的豁免。
