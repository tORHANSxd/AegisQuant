# P00 ADR 引用

| ADR | 状态 | P00 决策 | 关键证据 |
|---|---|---|---|
| `ADR-0001-runtime-and-version-policy.md` | Accepted | Python 3.13 正式线、3.14 候选线；精确前后端版本；以实际契约处理 pnpm/Next 文档漂移 | 依赖矩阵、两套 Python 契约、重复前端构建 |
| `ADR-0002-event-engine-selection.md` | Accepted | NautilusTrader 只作为候选事件回放核心；P00 不建交易适配器 | 固定三 tick 的双引擎经济状态哈希一致 |
| `ADR-0003-live-lock.md` | Accepted | 配置、代码、注册表、启动断言四重锁；无 P00 解锁路径 | 六项负向测试、前端只读锁定页 |

绝对决策文件位于 `docs/adr/`。三份 ADR 均不授予 Testnet、Canary 或 Live 权限；后续
若改变决策，必须新增 superseding ADR，不能原地抹除历史。
