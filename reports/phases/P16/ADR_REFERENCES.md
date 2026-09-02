# P16 ADR 引用

- `ADR-0021`：P16 组件版本、Alloy/Tempo 架构、私网与 mTLS 边界、加密备份、签名发布、失败安全回滚
  以及缺少 Docker 时不得冒充生产运行证据的直接决策。
- `ADR-0020`：P15 只读工作台、Read Model 和锁定 Node/pnpm 启动路径，是 P16 保护与观测的直接对象。
- `ADR-0019`：P14 PostgreSQL Read Model、只读 REST/WebSocket、CSP 与生成客户端边界。
- `ADR-0018`：P13 Paper/Shadow 运行、事故和故障演练语义，是 P16 告警与 Runbook 的运行上下文。
- `ADR-0010`：正式验收统一后置，阶段实现与自动化门禁完成不等于验收通过。
- `ADR-0003`：`LIVE_TRADING` 默认拒绝、失败安全与不可旁路锁定。
- `ADR-0001`：Python、Node、pnpm、PostgreSQL 与依赖版本政策。

P16 以各组件官方 release、OpenTelemetry 官方状态与 OTLP 规范、实际 registry digest 和仓库契约测试为
依据。任务书版本与收口时稳定版本不一致时采用官方稳定版本，并在 ADR-0021 中逐项锁定；Tempo 因
3.x 首版会引入 P16 不需要的 Kafka 架构而锁定 2.10.5，日志采集统一使用 Alloy，未引入 Promtail。
Windows 主机没有 Docker，因此最终证据明确区分静态配置验证、真实 PostgreSQL 恢复和目标 Linux
容器运行，后者保留为正式验收缺口。
