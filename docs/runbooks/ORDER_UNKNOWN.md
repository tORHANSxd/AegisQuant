# Order Unknown Runbook

## Detection and severity

- 订单提交、取消或改单结果超时且场所查询不能确定最终状态，触发 `ORDER_UNKNOWN`，默认 `SEV1`。
- 风险姿态立即进入 `HALTED` 或更安全状态，禁止重复发送。

## Immediate actions

1. 冻结该账户/策略的新订单命令，保留 client ID、venue ID、幂等键和请求时间线。
2. 只读查询订单、成交、余额和持仓，并从 Inbox/Outbox、执行事件、Fill、账本逐项对账。
3. 若场所事实仍不确定，升级人工处理并保持 `HALTED`。

## Forbidden actions

- 禁止猜测订单失败、复用新幂等键重发、修改本地状态冒充场所确认。
- 禁止用模型或 LLM 决定未知订单的经济事实。
- 禁止切换真实账户、写入或展示任何凭据。

## Evidence and recovery

- 保存 correlation/trace ID、原命令哈希、场所响应、查询快照、Fill、账本和对账结果。
- 只有订单终态已由场所事实证明、账本一致且人工批准后，才能在原非 Live 模式恢复。
