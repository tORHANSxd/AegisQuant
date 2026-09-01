# P08 ADR 引用

- `ADR-0001-runtime-and-version-policy.md`：Python 3.13 生产基线、Python 3.14 候选契约和精确锁定。
- `ADR-0003-live-lock.md`：`LIVE_TRADING=false`、真实账户隔离和执行锁。
- `ADR-0005-p02-columnar-data-foundation.md`：point-in-time 时间、内容寻址和数据证据基础。
- `ADR-0008-p04-multivenue-event-contracts.md`：Source Policy、证据 revision、冲突与事件来源边界。
- `ADR-0009-p05-accounting-policy.md`：权威净经济、成本和不可由模型结果替代的账本口径。
- `ADR-0010-deferred-acceptance-sequencing.md`：工程验证完成但正式验收延期，不生成
  `ACCEPTANCE.md`。
- `ADR-0011-p06-backtest-engine-policy.md`：历史规则、成本、撮合和公平回放边界。
- `ADR-0012-p07-feature-validation-baseline-policy.md`：PIT 数据集、OOF/时间验证、经典基线、
  最终 holdout 锁与 AI-Trader 许可证边界。
- `ADR-0013-p08-research-factory-model-ai-policy.md`：MLflow/Optuna、模型依赖、基础模型权重许可、
  Council 公平性、AI Proposal/RAG 安全、4070 Ti 延期和历史事件回放政策。

本阶段没有新增 waiver。`P08-A07` 是尚未执行的目标 GPU 正式验收项，不是被豁免的门禁。
