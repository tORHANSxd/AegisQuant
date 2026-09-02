# Restore From Backup Runbook

## Detection and severity

- 数据库不可恢复、权威状态损坏或灾备演练启动时使用；生产事故默认 `SEV0`。
- 恢复目标必须是隔离的一次性数据库，不能直接覆盖正在运行的权威实例。

## Immediate actions

1. 保持交易 `HALTED`，选择已校验 ciphertext/manifest 和正确的外部密钥引用。
2. 验证 encrypted SHA-256、AES-GCM 认证、明文包 SHA-256 后再运行 `pg_restore`。
3. 验证 Alembic revision、账本哈希链、逐资产借贷平衡、对账 payload 和 Read Model 计数。
4. 完成启动对账、Paper/Shadow smoke 和独立审批后，才允许切换数据库端点。

## Forbidden actions

- 禁止记录密钥或 DSN、恢复到 Live、跳过认证标签、覆盖唯一备份或先恢复后校验。
- 禁止在验证失败后自动重启交易。

## Evidence and recovery

- 保存备份 ID/哈希、key ID、源/目标验证摘要、RPO/RTO、操作者和审批者。
- 所有验证完全相等且人工批准后仅恢复原 Paper/Testnet；失败保持 `HALTED`。
