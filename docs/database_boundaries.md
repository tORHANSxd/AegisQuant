# PostgreSQL 与事务边界

## 权威存储

PostgreSQL 是 P01 的权威持久化系统。`domain` 包完全不知道数据库；
`persistence` 包使用 SQLAlchemy Core 和 Psycopg 3。P01 不引入 ORM entity、Redis、
Kafka 或 TimescaleDB，也不允许用 SQLite/Mock 代替 PostgreSQL 契约测试。

## 表边界

- `domain_events`：append-only 经济事实、schema version、时间、内容哈希和幂等键。
- `outbox_messages`：与经济事实在同一事务写入，待发布查询使用 `FOR UPDATE SKIP LOCKED`。
- `inbox_messages`：按 `consumer_name + message_id` 以及
  `consumer_name + idempotency_key` 双重去重。
- `provider_registry`、`source_document_registry`、`instrument_registry`、
  `event_schema_registry`：基础版本化 Registry。

## 写事务

```text
BEGIN
  INSERT domain_events ... ON CONFLICT DO NOTHING
  if inserted:
      INSERT outbox_messages ...
COMMIT
```

若 Outbox 插入失败，经济事件也回滚。重放同一 event ID、内容哈希或语义幂等键时，
不会写入第二个事实或第二条 Outbox。消费者先在业务事务内调用 Inbox 去重，再写
读模型；重复投递返回“未插入”，不再次应用副作用。

## 发布边界

Outbox worker（P01 不实现 worker）必须在短事务内锁定有限批次。外部发布成功后，
以条件更新写 `published_at`；崩溃发生在外部发布与本地确认之间时允许再次发布，
下游必须依靠 message/idempotency key 去重。这是 at-least-once 传输，不冒充
exactly-once 网络语义。

## Migration

- Alembic revision `20260831_0001` 是不可变 baseline。
- 发布后的 migration 不原地修改；修正通过新 revision。
- CI 从真实空库执行 `upgrade head`，核对表和约束，再执行 `downgrade base`。
- Alembic URL 只能在运行时通过 `AEGISQUANT_TEST_DATABASE_URL` 提供；仓库不保存 DSN、
  密码或 secret value。

## 临时测试服务器

Windows 测试使用 PostgreSQL 18.6 EDB x64 ZIP，SHA-256 为
`fbe23da234ee31547bf8a36d29dfd81e82b849df2d2b78d2eecb43d360252f8c`。
集群仅监听 `127.0.0.1` 随机端口，trust 认证只存在于一次性本地测试集群，不注册
Windows 服务、不监听局域网、不承载任何真实数据。测试停止后删除临时数据目录。
