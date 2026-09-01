# P10 ADR 引用

- `ADR-0001-runtime-and-version-policy.md`：Python 3.13 生产基线、3.14 候选契约与稳定依赖政策。
- `ADR-0003-live-lock.md`：`LIVE_TRADING=false`、真实账户隔离和执行锁。
- `ADR-0005-p02-columnar-data-foundation.md`：point-in-time 时间、来源 revision、内容寻址与不可变数据。
- `ADR-0008-p04-multivenue-event-contracts.md`：公共来源、事件采集、游标和外部访问边界。
- `ADR-0010-deferred-acceptance-sequencing.md`：工程验证完成但正式验收延期，不生成
  `ACCEPTANCE.md`。
- `ADR-0011-p06-backtest-engine-policy.md`：统一历史规则、成本、成交和公平回放口径。
- `ADR-0012-p07-feature-validation-baseline-policy.md`：PIT、反泄漏、时间验证、负结果和最终 Holdout 锁。
- `ADR-0013-p08-research-factory-model-ai-policy.md`：AI Proposal-only、Skeptic、证据子集和资源边界。
- `ADR-0014-p09-external-knowledge-safety-and-translation.md`：外部内容隔离、权利、翻译审计和不执行边界。
- `ADR-0015-p10-global-event-source-and-replay-policy.md`：vintage、多源许可、Jetstream v2、证据独立性、
  事件融合、回放与安全降级的 P10 决策。

本阶段没有新增 waiver。十项 P10 acceptance 行保持 `in_progress`，属于统一正式验收延期，不是
豁免或已接受。
