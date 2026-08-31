# P01 开放风险

以下风险不阻断 P01，但任何后续实现都不得把“契约骨架”吹成“可实盘系统”——这俩
差得不是一层窗户纸，是一整栋楼。

| ID | 级别 | 风险 | 当前约束 |
|---|---|---|---|
| P00-RISK-001 | medium | NautilusTrader 上游成熟度仍为 Beta | 仅确定性回放；不注册交易适配器 |
| P00-RISK-002 | medium | Windows 客户端并非明确的上游生产保证 | 以本机契约为证据；未来保留 WSL/受控容器选项 |
| P00-RISK-003 | low | 本机无 Docker、NVIDIA GPU 或 CUDA | P01 不依赖这些能力，不声称已验证 |
| P00-RISK-004 | low | 用户数据路径和可选 Provider 权限未提供 | 所有 Provider 继续默认拒绝 |
| P00-RISK-005 | low | Nautilus 回放触发 pandas UTC 弃用警告 | 两套 Python 契约通过；升级依赖前持续监控 |
| P00-RISK-006 | low | GitHub Actions 尚未在远程执行 | Actions 固定 SHA；完整本地 CI 为当前证据 |
| P00-RISK-007 | low | uv 创建次版本 junction 曾返回 exit 2 | 使用精确解释器路径；两套运行时均通过 |
| P01-RISK-001 | medium | EDB Windows ZIP 未发现独立上游签名/校验清单 | 仅从官方链接的 HTTPS 地址获取并固定本次 SHA-256；不用于生产部署 |
| P01-RISK-002 | medium | loopback PostgreSQL 测试集群使用 trust 认证 | 只在一次性随机端口和临时目录使用；不注册服务、不绑定外网、不复用数据目录 |
| P01-RISK-003 | medium | 领域对象、会计和订单目前是契约，不是完整引擎 | 后续阶段必须实现状态机、对账、风险和故障测试后才能声称能力 |
| P01-RISK-004 | low | 系统 Node.js 为 24.12.0，低于项目锁定 24.20.0 | 本地 CI 显式使用忽略目录中的 24.20.0；远程 CI 同版本固定 |

机器可读事实位于 `state/OPEN_RISKS.yaml`。任何风险升级为安全、可重复性、事务原子性
或 Live 锁失败时，阶段必须改为 `failed` 或 `blocked`，不得继续推进。
