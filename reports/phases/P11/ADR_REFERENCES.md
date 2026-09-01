# P11 ADR 引用

- `ADR-0001-runtime-and-version-policy.md`：Python 3.13 生产基线、3.14 候选契约与稳定依赖政策。
- `ADR-0003-live-lock.md`：`LIVE_TRADING=false`、真实账户隔离和执行锁。
- `ADR-0005-p02-columnar-data-foundation.md`：point-in-time 时间、来源 revision、内容寻址与不可变数据。
- `ADR-0010-deferred-acceptance-sequencing.md`：工程验证完成但正式验收延期，不生成
  `ACCEPTANCE.md`。
- `ADR-0011-p06-backtest-engine-policy.md`：统一成本、成交、保证金和压力回放口径。
- `ADR-0012-p07-feature-validation-baseline-policy.md`：PIT、反泄漏、时间验证、负结果和最终 Holdout 锁。
- `ADR-0013-p08-research-factory-model-ai-policy.md`：AI Proposal-only、Skeptic、证据与资源边界。
- `ADR-0016-p11-portfolio-independent-risk-policy.md`：组合提案、独立风险、签名政策、预交易门禁、
  单向安全状态和事件剧本的 P11 决策。

本阶段没有新增 waiver。七项 P11 acceptance 行保持 `in_progress`，属于统一正式验收延期，不是豁免
或已接受。
