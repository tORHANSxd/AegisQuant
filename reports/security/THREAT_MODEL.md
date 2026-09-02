# AegisQuant P16 Threat Model

## Scope and security objective

范围是单人 Paper/Shadow/Testnet 系统、只读 Web、可观测栈、PostgreSQL、备份、发布和研究环境。
Live Adapter、真实账户连接和 Live 解锁不在可用能力内。安全目标按优先级为：不发送真实订单、不泄露
秘密、风险不可绕过、账本/对账完整、point-in-time 正确、服务可恢复。

## Assets and trust boundaries

| Asset | Authority | Boundary |
|---|---|---|
| 订单、Fill、账本、对账 | PostgreSQL + 签名工件 | data 内部网络；不向 Web 直连 |
| 市场/事件/特征 | 不可变湖与清单 | research 与 execution 分离 |
| API/Web | 严格 Read Model | mTLS loopback reverse proxy |
| 指标/日志/追踪 | Prometheus/Loki/Tempo | observability 内部网络 |
| 凭据 | 外部秘密库/systemd credentials/Docker secrets | 不进 Git、日志、镜像或研究容器 |
| 备份 | AES-256-GCM ciphertext + manifest | 本地受限目录与独立离机卷 |
| 发布 | digest lock + Ed25519 manifest + 独立审批 | 构建与运行分离 |

Compose 的 `app`、`data`、`observability` 网络均为 internal；只有反向代理和 PostgreSQL 分别绑定
`127.0.0.1:8443`、`127.0.0.1:5432`。Web 入口要求 TLS 1.3 双向证书；Grafana禁匿名注册并另有管理
凭据。API/可观测服务不直接发布端口。

## Threats and controls

| Threat | Example | Preventive/detective control | Failure posture |
|---|---|---|---|
| Spoofing | 伪造操作者或 JWT | mTLS client CA；可选 EdDSA/RS256 issuer/audience/scope 验证；禁 HS 算法 | 401 / no route |
| Tampering | 改账本、备份、镜像 | 哈希链、双重记账、AES-GCM、SHA-256、registry digest、Ed25519 | HALTED |
| Repudiation | 无法追溯操作 | correlation/trace ID、JSON 日志、事故状态和独立审批 | 不允许恢复 |
| Information disclosure | 日志含 token/Cookie | 递归 key/value 脱敏、Alloy 内网、秘密扫描、无 Docker socket | HALTED + SECRET_LEAK |
| Denial of service | 磁盘满、队列积压、告警风暴 | 资源限制、去抖/分组/抑制、磁盘/CPU/内存告警、只读 API | DEGRADED/HALTED |
| Elevation | 研究读取交易秘密 | role→secret allowlist；research 零挂载；容器 drop ALL/no-new-privileges | startup reject |
| SSRF | 用户控制 OTLP/webhook URL | OTLP 仅 HTTPS 或 internal；webhook HTTPS/loopback、禁 userinfo/redirect | config reject |
| Supply chain | 恶意依赖/镜像漂移 | uv/pnpm lock、SBOM、SAST、dependency/license/secret scan、digest lock | deploy reject |
| Prompt injection | 外部文本要求工具/秘密 | 既有 SourceProcessingPolicy、proposal-only AI、无交易工具/秘密 | abstain |
| Recovery corruption | 损坏备份被恢复 | cipher/auth/hash/pg_restore/ledger/reconciliation/read-model 全链验证 | HALTED |

## Web security

- 主业务 API 只有 GET/OPTIONS，Trusted Host、loopback CORS、私有 ETag、CSP、frame deny、nosniff、
  no-referrer 和权限策略；错误响应不回显异常或鉴权细节。
- 反向代理限制请求率与 body，TLS 1.3 mTLS，关闭 server token 和 session ticket；所有页面带 CSP/HSTS。
- Grafana 禁匿名和注册，datasource 由服务端代理；浏览器不能直接访问 PostgreSQL、Loki、Tempo 或交易所。
- JWT 验证只接受非对称算法、固定 issuer/audience、到期与 `dashboard:read` scope；原 token 从不记录。

## Secret and key lifecycle

- Git 只保存秘密文件名和挂载策略，不保存值。秘密必须在用户本机秘密库、Docker secret 或
  `LoadCredentialEncrypted` 中创建、轮换和吊销。
- Research 角色允许秘密集合为空；Read API 最多可读取 OIDC 公钥/只读数据库引用；Testnet execution
  仅允许 Testnet key；`LIVE_API` 对所有角色永久拒绝。
- 发布私钥、审批私钥和备份密钥必须相互独立；代码只接收内存对象/32-byte key，不写私钥。

## Residual risks

- 当前 Windows 主机无 Docker，镜像未在本机启动或做运行时 CVE 扫描；目标 Linux 上必须补证据。
- 外部 SEV0/SEV1 用户渠道尚未配置，只有本地真实 webhook 契约可测试；正式到达证据待用户配置。
- mTLS CA、TLS 证书、Grafana 管理密码、PostgreSQL 密码和加密 systemd credential 由操作者在目标机创建；
  Codex 不接触其值。
- 首次目标 Linux 部署、离机卷和月度恢复演练未发生前，P18 必须保持 `NO_GO`。
