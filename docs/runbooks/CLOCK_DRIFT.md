# Clock Drift Runbook

## Detection

- 运行时钟与可信时间源偏差超过策略阈值或时间戳回退。
- 产生 `AQ-RUNTIME-CLOCK-FAULT`，运行状态锁存为 `HALTED`。

## Immediate actions

1. 停止所有新风险与时间敏感写入，保存本机、来源和数据库时钟证据。
2. 固定最后单调时间、检查点哈希、事件序列和告警时间线。
3. 由运维纠正主机时间后重新执行单调性与 PIT 契约测试。

## Forbidden actions

- 禁止手工回写时间戳、忽略回退或通过扩大阈值掩盖漂移。
- 禁止在时钟未知时恢复订单处理。
- 禁止使用真实账户或明文秘密验证连接。

## Evidence collection

- 漂移毫秒数、时间源、最后安全时间、检查点、对账和人工授权记录。

## Recovery conditions

- 时钟偏差回到阈值内且持续单调，检查点与对账通过。
- 必须由显式人工授权解除 `HALTED`，恢复模式不得升级。

## Drill record

- P13 使用 `FaultKind.CLOCK` 的 SEV1 模拟演练验证锁存和人工恢复门。
