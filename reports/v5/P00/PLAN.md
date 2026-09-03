# V5-P00 — Evidence Reset & SSOT Migration

- Evidence Tier: `DEVELOPMENT`
- Alpha Promotion Eligible: `false`
- Live Trading Locked: `true`

## Gap analysis

1. v5 计划已存在，但启动契约、规格索引和项目状态仍指向 v3.1。
2. 历史报告没有统一 EvidenceTier；fixture、synthetic 与 development 证据未硬隔离。
3. P06 golden 回测只有 5 秒，使用占位 SHA-256，却被只读 Dashboard 展示为账户收益。
4. v4.0/v4.1 源计划在工作树和 Git 历史中均不存在，不能伪造归档。
5. Live lock 当前有效，必须保持不变。

## 实施

1. 将 v5 设为当前 SSOT，新增独立 v5 状态并保留 v3.1 历史基线。
2. 建立 EvidenceTier 和 fail-closed Alpha Promotion 规则。
3. 为全部历史报告生成哈希绑定的 EvidenceTier 迁移索引及 fixture 审计。
4. 为 Workbench 增加机器可读证据披露，并把 P06 数值明确标为 fixture replay。
5. 运行 V5-P00 专项测试和完整 CI；失败则不得接受或进入 V5-P01。

## Acceptance

- 每个 `reports/v5` 之前的历史报告均在迁移索引中恰好出现一次并绑定 SHA-256。
- `FIXTURE`、`SYNTHETIC`、`DEVELOPMENT` 均不能用于 Alpha Promotion。
- Dashboard 不把 P06 fixture 显示为真实账户收益。
- `LIVE_TRADING=false`、`ORDER_SUBMISSION_ENABLED=false`，无真实账户连接。
- 完整 CI 通过；否则保留失败事实。
