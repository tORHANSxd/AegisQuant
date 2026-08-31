# P00 开放风险

以下风险均不阻断 P00，但不得被解释为后续阶段能力已具备：

| ID | 级别 | 风险 | 当前约束 |
|---|---|---|---|
| P00-RISK-001 | medium | NautilusTrader 上游成熟度为 Beta | 只允许确定性回放；无交易适配器 |
| P00-RISK-002 | medium | Windows 客户端不是明确的上游生产保证 | 以本机契约为 P00 证据；未来保留 WSL 选项 |
| P00-RISK-003 | low | 本机无 Docker、NVIDIA GPU 或 CUDA | 标记 unavailable，不声称容器/GPU 已验证 |
| P00-RISK-004 | low | 用户数据路径和可选来源权限均未提供 | 全部来源保持 `DENIED` |
| P00-RISK-005 | low | Nautilus 回放触发 pandas `Timestamp.utcnow` 弃用警告 | 契约通过；后续升级前继续监控上游 |
| P00-RISK-006 | low | GitHub Actions 尚未在远程执行 | Actions 固定 commit SHA；以本地完整 CI 为当前证据 |
| P00-RISK-007 | low | uv 创建次版本 junction 时曾返回 exit 2 | 使用精确解释器路径；两套运行时契约均通过 |

机器可读事实位于 `state/OPEN_RISKS.yaml`。任何风险升级为安全、可重复性或 Live 锁失败
时，阶段状态必须改为 `failed` 或 `blocked`，不得继续推进。
