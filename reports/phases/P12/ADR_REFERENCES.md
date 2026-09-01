# P12 ADR 引用

- `ADR-0001-runtime-and-version-policy.md`：Python 3.13 生产基线、3.14 候选契约与稳定依赖政策。
- `ADR-0003-live-lock.md`：`LIVE_TRADING=false`、真实账户隔离与执行锁。
- `ADR-0005-p02-columnar-data-foundation.md`：事件时间、可用时间、内容寻址与不可变证据约束。
- `ADR-0010-deferred-acceptance-sequencing.md`：工程验证完成但正式验收延期，不生成
  `ACCEPTANCE.md`。
- `ADR-0011-p06-backtest-engine-policy.md`：成本、成交、保证金与回放口径不能冒充真实执行结果。
- `ADR-0016-p11-portfolio-independent-risk-policy.md`：执行输入必须来自独立风险批准的有效
  `OrderIntent`。
- `ADR-0017-p12-testnet-execution-recovery-policy.md`：Testnet/模拟边界、Nautilus 固定版本契约、
  经济幂等、未知状态恢复、账户对账、原子资金事实和无凭据阻塞口径。

本阶段没有新增 waiver。`P12-A01` 为 `blocked_external_input`，其余六项 acceptance 保持
`in_progress`；这些状态是统一正式验收延期与真实外部前置条件的如实记录，不是已接受。
