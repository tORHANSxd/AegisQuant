# Database Failure Runbook

## Detection

- 提交事务、检查点持久化或读取校验失败，产生 `AQ-RUNTIME-DATABASE-FAULT`。
- 运行状态必须锁存为 `HALTED`，不得继续新增风险。

## Immediate actions

1. 停止创建订单、Fill、账本投影和 Read Model 事件。
2. 保存事务 ID、最后提交序列、数据库健康证据、检查点哈希和告警时间线。
3. 将任何结果不明事务标为待人工核验，不做猜测性重试。

## Forbidden actions

- 禁止绕过数据库直接推进内存权威状态。
- 禁止清空幂等索引、重建未知 Fill 或自动改写对账差异。
- 禁止接触真实交易账户或写入任何明文秘密。

## Evidence collection

- 失败事务边界、提交/回滚结果、订单/Fill/账本/Outbox 计数和恢复检查点。
- 故障前后权威状态哈希与每日对账结果。

## Recovery conditions

- 数据库健康、检查点完整、事务结果已确认、重复经济事实为零且每日对账为 `CLEAR`。
- 必须由显式人工授权解除 `HALTED`；恢复后仍处于原 Paper/Shadow 模式。

## Drill record

- P13 使用 `FaultKind.DATABASE` 的 SEV0 模拟演练；没有真实资金影响。
