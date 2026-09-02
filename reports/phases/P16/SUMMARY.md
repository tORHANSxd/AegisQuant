# P16 实施总结

P16 已完成任务书第 18 章的可观测、安全、部署、备份恢复与发布回滚实现。应用现可用同一相关 ID
关联低基数 Prometheus 指标、脱敏 JSON 日志和 OpenTelemetry trace/span；生产配置接入 Prometheus、
Grafana、Loki、Alloy、Alertmanager 与 Tempo，且没有使用已结束支持的 Promtail。六类不可编辑仪表盘
覆盖业务、交易、风险、数据、模型与基础设施，每类均固化 4 个低基数面板。

告警基线覆盖 SEV0—SEV3、去抖、抑制、维护窗口、升级路由和事故生命周期。仓库内 loopback webhook
契约已证明 SEV0 可以投递，但没有用户配置的外部渠道，因此不能声称 SEV0/SEV1 已真正到达用户。
第 18 章要求的 12 份 Runbook、事故模板、威胁模型和 Paper/Testnet 部署手册均已建立；研究服务不挂载
交易秘密，所有角色均被拒绝读取 Live 秘密，API 默认只监听私网/loopback 并具备 mTLS、CSP 和可选
离线 OIDC JWT 契约。

备份演练使用 PostgreSQL 18.6 原生 custom dump、AES-256-GCM 和 SHA-256 清单，在一次性数据库恢复后
验证 2 条账本事件、9 条分录及 1 个对账案例，账本平衡、哈希链和对账均通过；篡改密文被拒绝。
发布清单使用 Ed25519 签名、到期时间和人工审批门，任一验证、迁移、健康检查或对账失败都保持
`HALTED/REDUCE_ONLY`，回滚后也必须人工恢复，不存在自动恢复交易路径。

完整流水线 51/51 通过：Python 3.13 为 650 项通过，Python 3.14.7 隔离候选环境为 611 项通过，均有
11 条上游弃用告警；P16 定向测试 30 项通过，变异测试 6/6 全部击杀。Bandit、秘密、依赖、许可证、
SBOM 和容器/IaC 静态门禁均通过，秘密发现数为 0。

当前 Windows 主机没有 Docker，故只完成应用契约、静态 Compose/IaC 检查、镜像 digest 锁和真实
PostgreSQL 恢复；没有伪造目标 Linux 容器启动、运行时镜像扫描或异机备份证据。按业主决定，本阶段
没有运行 12h/24h 墙钟验收，也不生成 `ACCEPTANCE.md`。以上只证明 P16 实现和自动化门禁完成，
不等于正式验收；没有连接真实账户或交易场所网络，没有索取或写入明文秘密，`LIVE_TRADING` 继续锁定。
