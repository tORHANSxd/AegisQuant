# Reconciliation Failure Runbook

## Detection and severity

- 余额、持仓、订单、Fill 或账本差异非零，或权威对账无法完成，触发 `SEV0`。
- `new_orders_allowed=false`，运行姿态锁存为 `HALTED`。

## Immediate actions

1. 停止所有新增风险，只允许只读查询、证据保存和预先批准的减仓流程。
2. 固化本地/场所快照、available time、数据版本、差异分类和最后清晰对账点。
3. 按订单→Fill→账本→持仓→余额顺序定位第一处权威事实分叉。

## Forbidden actions

- 禁止自动冲销、静默容差扩大、删除差异或把聚合数据当场所权威事实。
- 禁止恢复交易来“试试看是否好了”。

## Evidence and recovery

- 保存差异明细、原始快照哈希、修复事件、重放结果、账本状态哈希和审批者。
- 差异归零、账本重放一致、连续两次启动对账为 `CLEAR` 且人工批准后才可恢复。
