# P18 开放风险

- **approved-strategy-scope（高，开放）**：At most one fully evidenced strategy and bounded instrument scope is selected；`AQ-P18-NO-APPROVED-STRATEGY`。
- **dedicated-account-controls（高，开放）**：Dedicated low-balance, no-withdrawal, IP allowlisted least-privilege account exists；`AQ-P18-ACCOUNT-CONTROLS-NOT-PROVIDED`。
- **real-testnet-duration-fills（高，开放）**：Real Testnet duration, fills, reconciliation and fault evidence passes；`AQ-P18-REAL-TESTNET-NOT-ACCEPTED`。
- **external-alert-and-oncall（高，开放）**：External SEV0/SEV1 delivery and human on-call window are verified；`AQ-P18-EXTERNAL-ALERT-ONCALL-NOT-VERIFIED`。
- **target-linux-runtime（高，开放）**：Target Linux container runtime and image behavior are verified；`AQ-P18-TARGET-LINUX-RUNTIME-NOT-VERIFIED`。
- **offsite-backup（高，开放）**：Encrypted backup exists on a distinct offsite device and restores successfully；`AQ-P18-OFFSITE-BACKUP-NOT-VERIFIED`。
- **wall-clock-stability（高，开放）**：Required wall-clock stability acceptance is complete；`AQ-P18-WALL-CLOCK-ACCEPTANCE-DEFERRED`。
- **正式验收延期（高，开放）**：自动门禁完成不等于 P05–P18 正式 acceptance；按用户决定不执行 12h/24h。
- **上游弃用告警（低，开放）**：Starlette/httpx2 与 Nautilus/Pandas timedelta 告警需在依赖升级时回归。
