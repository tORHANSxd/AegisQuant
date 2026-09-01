# Process Crash Runbook

## Detection

- 心跳消失、进程退出或故障注入产生 `AQ-RUNTIME-PROCESS-FAULT`。
- 在重启预算内进入 `RECOVERING`；预算耗尽则 `HALTED`。

## Immediate actions

1. 从最后内容哈希有效的检查点恢复，不清空订单、Fill、已处理事件或经济幂等索引。
2. 恢复后先运行订单/Fill/账本/Read Model 对账，再允许新增风险。
3. 保存退出码、最后心跳、检查点哈希、重启次数和恢复时间线。

## Forbidden actions

- 禁止无检查点启动为空状态，禁止重发结果不明订单。
- 禁止超过重启预算继续自旋，禁止自动升级为 Testnet 或 Live。
- 禁止索取、读取或记录明文密码、Cookie、验证码或 API Secret。

## Evidence collection

- 进程退出证据、检查点内容哈希、恢复前后 ID 集合、重复计数和对账结果。

## Recovery conditions

- 检查点有效，模式一致，重启预算未耗尽，重复订单/Fill/账本均为零，对账为 `CLEAR`。

## Drill record

- P13 使用 `FaultKind.PROCESS` 的 SEV0 模拟演练；加速稳定性中计划执行一次恢复。
