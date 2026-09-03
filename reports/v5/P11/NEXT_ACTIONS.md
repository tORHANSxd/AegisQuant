# V5-P11 后续动作

- 持续运行真实 wall-clock Paper 与只读 Shadow，至少覆盖 30 个日历日。
- 按预提交策略积累足够独立事件；不足则 `EXTEND_PAPER`，不降低门槛。
- 连续采集 predicted-vs-realized Truth、Forecast、Cost 与 event increment，并记录漂移。
- 将 heartbeat、incident、checkpoint 与 recovery receipt 写入受保护的不可变存储或透明日志。
- P12 只做 Testnet/Canary readiness；七项硬门未全 PASS 前不得生成 `CANARY_REVIEW_READY`。
