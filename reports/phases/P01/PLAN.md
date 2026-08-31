# P01 实施计划

## 目标

建立不依赖交易所、数据库和 Web 框架的纯领域核心，以及 PostgreSQL
事件、Outbox、Inbox 和基础 Registry 持久化骨架。P01 只固化领域语义、契约、
事务边界和可验证的不变量，不实现完整交易、会计、风险或数据采集能力。

## 规格基线

- 规格版本：`3.1.0`
- 根规格：`AegisQuant_v3.1_Multimodal_Event_Intelligence_Codex_Master_Taskbook.md`
- 根规格 SHA-256：`1265a4feeb126bf9004685b80c0aa01d053fd983079b80d5c9063abefc382d1f`
- P00 状态：`accepted`
- P01 执行批准时间：2026-08-31
- 安全默认值：`LIVE_TRADING=false`

## 范围

1. 强类型内部 ID、UTC-only 时间语义、可注入 `Clock`。
2. 拒绝普通 float 的 Decimal `Money`、`Quantity`、`Price` 值对象。
3. Instrument、Venue、Asset、Account、Environment 等基础领域对象。
4. 任务书指定的事件情报、预测、信号、提案和风险判定对象。
5. SourceProcessingPolicy 在采集、推理、展示、删除边界上的 fail-closed 判定。
6. OrderIntent、OrderCommand、VenueOrder、Fill 和恢复案例的领域契约。
7. JournalEntry、LedgerPosting、PositionLot schema 及阶段内可验证不变量。
8. 版本化序列化、事件 JSON Schema、兼容迁移、统一错误分类。
9. 严格配置 schema、未知字段拒绝、规范化内容哈希。
10. PostgreSQL 18.6、SQLAlchemy 2、Alembic、Psycopg 3 的持久化骨架。
11. Inbox、Outbox、幂等键和基础 Registry 表及真实 PostgreSQL 事务测试。
12. 领域、属性、契约、架构、迁移和回滚测试。

## 实施顺序

1. 更新阶段状态和规范追踪生成器，将 P00 固化为历史证据并将 P01 标为进行中。
2. 锁定正式依赖并记录 PostgreSQL 与 Python 库版本选择 ADR。
3. 实现纯领域包、值对象、策略判定、错误目录和版本化事件信封。
4. 生成事件与配置 JSON Schema，建立 round-trip 和 schema migration 测试。
5. 在独立 persistence 包中实现数据库 metadata、事务边界和消息幂等操作。
6. 建立不可变 Alembic baseline migration，并使用临时 PostgreSQL 实例验证升降级。
7. 运行全量静态、单元、属性、契约、安全、供应链和前端回归门禁。
8. 生成 P01 阶段八件套、工件清单、验收状态和 Git 证据。

## 验证门禁

- `domain` 包不得导入 FastAPI、SQLAlchemy、Alembic、Psycopg 或交易所 SDK。
- naive datetime 构造和无时区输入必须被静态或运行时检查拒绝。
- Money、Quantity、Price 不接受 float，且拒绝 NaN、Infinity 和负零。
- 事件 Python/JSON/JSON Schema round-trip 保留 Decimal 经济字段和 schema version。
- SourceProcessingPolicy 未明确批准时在四个边界全部拒绝。
- Inbox 重放不能重复消费，Outbox 幂等发布不能生成第二个经济事实。
- 空 PostgreSQL 数据库可以 `upgrade head` 并完整 `downgrade base`。
- 关键金额、时间、状态、序列化和幂等不变量通过 Hypothesis 属性测试。
- 所有 P00 安全基线回归通过，`LIVE_TRADING` 始终保持锁定。

## PostgreSQL 测试边界

使用 EDB 提供、由 PostgreSQL 官方 Windows 下载页链接的 PostgreSQL 18.6 x64 ZIP。
二进制仅解压到 Git 忽略的 `.tools/`；测试集群仅监听 `127.0.0.1` 随机端口，
使用一次性数据目录，不注册 Windows 服务，不创建外部账户，不保存密码。

## 非目标

- 不连接真实交易账户、Testnet、私有数据源或交易所私有 API。
- 不提供任何 Live 解锁路径，不实现订单发送 Adapter。
- 不实现完整双重记账、组合优化、风险引擎、订单状态机或恢复编排器。
- 不引入 Redis、Kafka、TimescaleDB、Kubernetes、API 服务或 Web 业务页面。
- 不开始 P02。

## 失败策略

任何硬门失败且无法在 P01 范围内修复时，阶段必须保留真实证据并标记为
`blocked` 或 `failed`。禁止通过 Mock PostgreSQL、skip、占位实现、降低安全门槛或
删减不变量宣称验收通过。
