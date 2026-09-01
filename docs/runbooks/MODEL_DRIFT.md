# Model Drift or Failure Runbook

## Detection

- 模型版本不可用、推理超时、模型年龄超阈值或漂移门触发 `AQ-RUNTIME-MODEL-FAULT`。
- 运行状态进入 `DEGRADED`，禁止新增风险。

## Immediate actions

1. 固定失败模型版本、输入特征哈希、预测 ID、超时或漂移指标。
2. 停止新预测进入风险决策；已存在的订单事实只允许只读对账。
3. 核验候选模型工件、训练清单和版本签名。

## Forbidden actions

- 禁止无证据回退到未批准模型或悄悄放宽阈值。
- 禁止复用过期预测、补写置信度或把 Paper 结果当收益保证。
- 禁止访问真实交易凭据。

## Evidence collection

- 模型版本、工件哈希、输入可用时点、错误类型、告警和恢复验证结果。

## Recovery conditions

- 已批准模型可复现加载，健康推理通过，模型年龄与漂移重新低于阈值。
- 恢复前确认没有故障期间的新风险事实，模式不变。

## Drill record

- P13 使用 `FaultKind.MODEL` 模拟不可用与陈旧状态并保存时间线。
