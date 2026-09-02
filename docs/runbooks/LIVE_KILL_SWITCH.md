# Live Kill Switch Runbook

## Detection and severity

- kill switch 激活、Live 解锁路径出现或任何真实下单尝试均为 `SEV0`。
- 当前系统的 `LIVE_TRADING` 必须永久保持锁定；本 Runbook 不提供解锁步骤。

## Immediate actions

1. 保持 `HALTED`，隔离所有执行进程和网络出口，保存策略/风险/执行/配置哈希。
2. 确认 Live Adapter 未注册、真实账户未连接、真实订单请求计数为零。
3. 检查发布清单、审批记录、秘密挂载和最近变更，必要时回滚到已验证版本。

## Forbidden actions

- 禁止通过环境变量、数据库、Web、脚本或人工命令解除锁。
- 禁止用真实账户验证防护，也禁止让 AI 决定恢复。

## Evidence and recovery

- 保存 kill switch 状态、网络证据、代码/工件签名、回滚和全量安全测试结果。
- 只能恢复 Paper/Shadow/Testnet；任何 Canary/Live 仍须 P18 后单独人工流程，本阶段不可执行。
