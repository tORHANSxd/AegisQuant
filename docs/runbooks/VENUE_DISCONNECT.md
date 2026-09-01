# Venue Disconnect Runbook

## Detection

- 公共行情心跳超时、序列停止推进或网络故障注入产生 `AQ-RUNTIME-NETWORK-FAULT`。
- 运行状态必须进入 `DEGRADED`，`new_risk_allowed=false`。

## Immediate actions

1. 冻结新增风险决策和新 Paper/Shadow 决策输出。
2. 保存最后成功行情序列、时间戳、来源哈希、运行检查点和告警 ID。
3. 使用离线健康探测确认公共行情恢复；不得用交易写接口探测。

## Forbidden actions

- 禁止切换到真实账户、Testnet 下单或 Live 域名。
- 禁止跳过缺失行情序列、伪造心跳或用未来数据补当前决策。
- 禁止索取或记录密码、Cookie、验证码或 API Secret。

## Evidence collection

- 告警、故障开始/恢复时点、最后与首个恢复序列、检查点哈希和对账结果。
- 网络请求计数必须证明交易场所写请求为零。

## Recovery conditions

- 公共行情连续推进，时间单调，缺口已明确处理，数据年龄低于策略阈值。
- 检查点哈希有效、对账无差异、恢复模式与故障前一致。

## Drill record

- P13 使用 `FaultKind.NETWORK` 确定性注入；结果写入 `reports/runtime/P13_INCIDENT_DRILLS.json`。
