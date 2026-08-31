# P00 实施计划

## 目标

从空目录建立可重复、默认安全、可由 Codex 持续执行的 AegisQuant v3.1 工程基线。只实施 P00；不创建 P01 领域模型、数据库骨架、交易适配器或任何真实账户连接。

## 规格基线

- 规格版本：`3.1.0`
- 根规格：`AegisQuant_v3.1_Multimodal_Event_Intelligence_Codex_Master_Taskbook.md`
- 根规格 SHA-256：`1265a4feeb126bf9004685b80c0aa01d053fd983079b80d5c9063abefc382d1f`
- 执行批准时间：2026-08-31
- 安全默认值：`LIVE_TRADING=false`

## 范围

1. 固化规格副本、规格索引和完整需求追踪矩阵。
2. 初始化源码 Git `main`，提供分支保护建议与本地 CI。
3. 建立可重建的完整目录清单，不生成未来阶段的空业务实现。
4. 探测并记录主机、WSL、硬件、磁盘、网络和工具链能力。
5. 锁定 Python 3.13 主环境；对 Python 3.14 做候选兼容测试。
6. 建立 uv、Ruff、Pyright strict、pytest、pre-commit 和安全扫描。
7. 对 NautilusTrader 最新非预发布 v1 版本执行安装、导入、最小确定性回放、许可证和兼容测试。
8. 建立 Node 24 LTS、pnpm、Next.js 16、React 19、TypeScript strict 的最小可构建锁定页。
9. 实现配置、代码硬保护、Adapter Registry 和测试四层 Live 锁。
10. 建立 `SourceProcessingPolicy` schema、默认拒绝策略、来源许可矩阵、事件本体初稿、官方来源与实体模板。
11. 生成不含秘密值的访问请求、威胁模型、安全政策、SBOM 和许可证材料。
12. 运行全部 P00 门禁，生成阶段八件套和全局状态；失败则标记 `blocked` 或 `failed` 并停止。

## 非目标

- 不连接任何真实交易账户、Testnet 账户或私有数据源。
- 不请求或写入密码、Cookie、验证码、API Secret、Token 或会话文件。
- 不实现 P01 的领域对象、事件持久化、数据库或 Outbox。
- 不引入 Tailwind、shadcn/ui、Storybook、数据库、Redis、Kafka、Kubernetes 或业务微服务。
- 不创建可发送订单的 Adapter、命令或网页入口。

## 实施顺序

1. 规格与追踪：建立规格索引、规范子句抽取器、完整 CSV 和覆盖测试。
2. 仓库与目录：初始化 Git/main；复制并哈希规格；建立目录清单和幂等引导脚本。
3. Python 基线：建立 `pyproject.toml`、uv 锁、严格静态检查和最小包。
4. 安全基线：实现 Live fail-closed、防副作用导入和默认拒绝来源政策。
5. Event Engine：锁定 NautilusTrader，执行确定性最小回放和 3.13/3.14 兼容矩阵。
6. Web 基线：建立纯 Server Component 锁定页和前端测试、构建。
7. 供应链与治理：生成 SBOM、许可、漏洞、秘密扫描、ADR、威胁模型和访问请求。
8. 验证与证据：运行本地 CI，生成报告、清单、状态和 Git 证据。
9. 归档：按 `.codex-git.toml` 的显式 archive 模式存档一次，随后停止。

## 验证门禁

- 规格副本 SHA-256 与根规格完全一致。
- 每个硬规范子句在追踪矩阵中恰有一项映射；P00 项必须有可执行验证工件。
- `uv lock --check`、frozen sync、Ruff、Pyright strict、pytest 和 pre-commit 通过。
- NautilusTrader 安装、导入和两次最小回放经济摘要哈希一致。
- pnpm frozen install、ESLint、TypeScript strict、Vitest 和 Next.js build 通过。
- `LIVE_TRADING=true` 等单一环境变量不能启用 Live；不存在 Live Adapter。
- 导入测试检测不到网络、秘密读取或订单副作用。
- secret scan 零命中；SBOM、许可证和依赖审计有机器可读结果。
- P00 强制报告、状态和工件哈希通过 schema/一致性检查。

## 失败策略

任何硬门失败且无法在 P00 内修复时，更新 `PROJECT_PHASE_STATE.yaml` 为 `blocked` 或 `failed`，保留真实测试证据并停止。不得通过 skip、占位结果或降低安全门槛宣称验收通过。
