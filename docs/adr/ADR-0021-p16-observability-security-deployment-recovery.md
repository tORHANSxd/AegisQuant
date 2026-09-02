# ADR-0021：P16 可观测、安全、部署与恢复基线

- 状态：Accepted
- 日期：2026-09-02
- 决策范围：P16

## 背景

任务书要求在 P16 接入 Prometheus、Grafana、Loki、Alloy、Alertmanager 与 OpenTelemetry，并提供安全
部署、加密备份、恢复和回滚。版本与任务书编写时点已发生变化，本机也没有 Docker，因此必须区分
“配置和应用契约已验证”与“容器在目标 Linux 主机实际运行已验证”。

## 决策

1. 生产 Compose 只使用精确版本：Prometheus `3.14.0`、Alertmanager `0.34.0`、Grafana
   `13.2.0`、Loki `3.7.7`、Grafana Alloy `1.19.2`、Tempo `2.10.5`。禁止 `latest`；部署前还须用
   `infra/compose/IMAGE_LOCK.json` 中记录的 registry digest 校验镜像。
2. Python 使用精确锁定的 `prometheus-client`、`opentelemetry-sdk` 与 OTLP/HTTP exporter。OpenTelemetry
   负责 trace，Prometheus client 负责应用指标，标准库 JSON logger 负责日志；这是因为官方当前把 Python
   traces/metrics 标为 Stable，而 logs 仍为 Development。
3. Alloy 是唯一日志和 OTLP 采集代理；不引入已结束支持的 Promtail。Tempo 锁定最后一代稳定 2.x 并作为
   单机 trace backend，避免 Tempo 3.x 新架构把 Kafka 带回首版；Loki 使用文件系统单体模式，不引入
   Kafka、Kubernetes 或多租户复杂度。
4. Grafana、Prometheus、Loki、Tempo 和 Alertmanager 均只绑定内部 Compose 网络。唯一发布端口绑定
   loopback，并由 TLS 1.3 双向证书认证反向代理保护；API 另保留可选离线 OIDC JWT 验证器。默认配置
   不包含凭据，秘密只能通过只读文件或环境变量名称引用。
5. 备份使用 PostgreSQL 原生工具产生可恢复转储，再以 AES-256-GCM 加密并附 SHA-256 清单；恢复必须进入
   一次性数据库，并运行迁移、账本与对账验证后才算通过。
6. 发布清单使用 Ed25519 签名和到期时间。任何验证、迁移、健康检查或对账失败都只能回到
   `HALTED/REDUCE_ONLY`，绝不自动恢复交易。
7. 当前 Windows 主机没有 Docker。P16 只声明通过静态配置、应用契约和原生 PostgreSQL 恢复演练；
   容器启动、镜像运行扫描、用户外部告警渠道与目标 Linux 部署保留为正式验收证据缺口。

## 官方依据

- Prometheus releases: https://github.com/prometheus/prometheus/releases
- Alertmanager releases: https://github.com/prometheus/alertmanager/releases
- Grafana releases: https://github.com/grafana/grafana/releases
- Loki releases: https://github.com/grafana/loki/releases
- Grafana Alloy releases: https://github.com/grafana/alloy/releases
- Grafana Tempo releases: https://github.com/grafana/tempo/releases
- OpenTelemetry Python status: https://opentelemetry.io/docs/languages/python/
- OTLP exporter specification: https://opentelemetry.io/docs/specs/otel/protocol/exporter/

## 后果

- 依赖和部署输入可复现，采集链路没有 Promtail，也没有首版不需要的集群组件。
- 本机可以完整验证应用、告警、签名、恢复和安全契约，但不得把缺失 Docker 的静态检查冒充生产运行。
- P18 在缺少真实用户渠道、目标 Linux 容器运行和人工审批证据时必须保持 `NO_GO`。
