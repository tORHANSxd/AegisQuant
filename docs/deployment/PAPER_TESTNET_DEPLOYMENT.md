# Paper/Testnet Deployment Handbook

## Hard boundary

本手册只允许 `PAPER` 或 `TESTNET`。不得创建 Live profile、注册 Live Adapter、连接真实账户或通过任何
环境变量解除 `LIVE_TRADING`。任何失败都保持 `HALTED`，回滚后也必须人工复核才能恢复。

## Target prerequisites

- 独立 Linux LTS 主机、Docker Engine/Compose plugin、PostgreSQL 18 client、chrony、systemd。
- 仅 loopback 入口；需要远程访问时由操作者建立受控 VPN/SSH tunnel，禁止公网裸露端口。
- 独立加密离机挂载 `/mnt/aegisquant-offsite`，空间和权限已验证。
- TLS server certificate、operator client CA、Grafana/PostgreSQL 密码和备份密钥仅在目标机秘密库创建。
  不得在聊天、Git、shell history 或报告中粘贴其值。

## Build once and freeze

1. 在隔离构建机以 `infra/docker/Dockerfile.api` 和 `Dockerfile.web` 构建一次。
2. 运行 Python/Web 全量 CI、SBOM、SAST、依赖、许可证、秘密扫描和镜像扫描。
3. 记录 API/Web manifest digest；与 `infra/compose/IMAGE_LOCK.json` 的第三方 digest 一起冻结。
4. 生成 Ed25519 Release Manifest，由不同密钥/操作者独立审批；清单最多 24 小时有效。
5. 将只读工件复制到 `/opt/aegisquant`。目标主机只 pull digest，不 build、不使用 `latest`。

## Configure without exposing secrets

- `/etc/aegisquant/compose.env` 只保存 profile、环境、镜像名称/digest、秘密目录路径和已渲染
  Alertmanager 配置路径，不保存密码或 token。
- 使用目标机秘密管理工具创建 Compose secret 文件及 systemd encrypted credentials；权限最小化。
- 在目标机本地设置 `AEGISQUANT_OPERATOR_WEBHOOK_URL`，运行
  `python scripts/render_alertmanager_config.py --output <restricted-path>`；输出路径加入 compose.env。
- 先运行 `docker compose --profile paper config --quiet`，确认仅 loopback 发布 8443/5432、无 Promtail、
  无 Live、无 Docker socket、无 `latest`。

## Migration and deploy

1. 启动前执行加密备份；若离机复制或哈希验证失败，停止。
2. 将交易姿态置 `HALTED`，运行向前兼容 Alembic migration；不允许破坏性降级覆盖数据。
3. 启动 `paper` profile，等待所有 health check。检查 chrony、磁盘、内存、CPU、Prometheus targets。
4. 运行 Read API/mTLS/Grafana smoke、事件 replay、账本哈希链、双重记账与启动对账。
5. 验证 SEV0/SEV1 测试告警到达配置渠道并记录接收时间；验证日志↔trace↔metric 关联。
6. 由操作者签字后仅恢复 `PAPER_ACTIVE`。Testnet 还须独立审批和专用 Testnet 最小权限账户。

## Rollback

1. 任一 migration、health、smoke、告警、账本或对账失败：停止新风险，保持 `HALTED`。
2. 选择上一份已验证 digest/签名清单；不得在目标机重建或修改镜像。
3. 仅在 schema 前向兼容时切回旧应用；否则从加密备份恢复到隔离数据库并验证。
4. 回滚成功不等于恢复交易。重新运行 smoke、replay、账本和对账，再由人工批准 Paper/Testnet 恢复。

## Backup and restore operations

- `aegisquant-backup.timer` 每日创建 PostgreSQL custom dump，打包关键状态，以 AES-256-GCM 加密，
  校验后只复制 ciphertext 和 manifest 到独立挂载。
- 每月按 `RESTORE_FROM_BACKUP.md` 在一次性数据库执行恢复演练，记录 RPO/RTO、源/目标验证摘要。
- 严禁 `docker compose down -v`；卷清理必须独立变更、先确认备份且精确列出目标。

## Testnet delta

- 只允许专用 Testnet 账号、无提现能力、最小 API 权限、IP allowlist；凭据只进 Testnet execution 容器。
- Research、Web、Grafana、Alloy 和 API 不挂载 Testnet key。未知订单先对账，禁止盲目重发。
- Testnet 结果不证明 Live 盈利或就绪；P18 仍默认 `NO_GO`。
