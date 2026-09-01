# Stale Data Runbook

## Detection

- 行情或事件 `available_at` 年龄超过策略阈值、序列不推进或来源校验失败。
- 产生 `AQ-RUNTIME-DATA_SOURCE-FAULT` 并进入 `DEGRADED`。

## Immediate actions

1. 阻断使用陈旧数据的新预测、目标和订单。
2. 保存来源 ID、内容哈希、事件/可用/接收时间及最后连续序列。
3. 验证恢复数据不包含 look-ahead，必要时显式标记缺口。

## Forbidden actions

- 禁止用接收时间冒充事件时间、用未来数据补当前决策或静默插值关键缺口。
- 禁止把归一化历史夹具冒充交易所逐笔原始数据。
- 禁止连接真实账户或记录任何秘密值。

## Evidence collection

- 陈旧时长、序列缺口、来源哈希、受影响 trace、告警和恢复后的连续样本。

## Recovery conditions

- 数据年龄低于阈值，事件/可用/接收时间单调，来源哈希有效且缺口处理有记录。
- 故障期间无新增风险，对账无差异。

## Drill record

- P13 使用 `FaultKind.DATA_SOURCE` 和超龄心跳两条路径验证降级。
