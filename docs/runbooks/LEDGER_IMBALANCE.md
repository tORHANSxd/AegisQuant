# Ledger Imbalance Runbook

## Detection and severity

- 任一 JournalEntry 按资产借贷不平、哈希链断裂、账本落后 Fill 超预算或快照签名失败，触发 `SEV0`。
- 账本是 PnL 权威来源，故所有新增风险必须停止。

## Immediate actions

1. 进入 `HALTED`，冻结数据库写入范围并保存最后已验证 ledger sequence/hash。
2. 在只读副本重放事件与账本，定位首个不变量失败记录。
3. 校验关联 Fill、订单、Outbox、模板版本和会计政策哈希。

## Forbidden actions

- 禁止直接编辑 Posting、跳过损坏事件、重置哈希链或用 Read Model 覆盖权威账本。
- 禁止以容差掩盖非舍入差异。

## Evidence and recovery

- 保存损坏序列、双重记账验证、重放摘要、恢复快照签名和对账结果。
- 只能从已验证备份恢复或追加获批纠正分录；完整重放、平衡和对账通过后人工恢复。
