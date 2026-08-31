# P01 验收记录

## 决定

P01 验收通过。验收对象为实现提交
`581f39b52d90455346fb42e58a7dff133fb370a1`，证据生成于 2026-08-31。阶段状态可从
`in_progress` 更新为 `accepted`，但不得自动开始 P02。

## 任务书验收项

| 验收项 | 结果 | 证据 |
|---|---|---|
| `domain` 无 FastAPI、ORM、交易所 SDK | PASS | `tests/architecture/test_domain_boundaries.py` 静态导入边界；Pyright strict 通过 |
| 无 naive datetime，静态检查可阻止 | PASS | UTC 类型/构造校验及 AST 架构测试 |
| Money/Quantity 不与普通 float 隐式混合 | PASS | 值对象严格验证、单元测试和 Hypothesis 属性测试 |
| 事件 round-trip 保持经济字段与版本 | PASS | canonical JSON、version registry、JSON Schema 契约测试 |
| Inbox/Outbox 重放不重复消费 | PASS | 真实 PostgreSQL Inbox 冲突与 Outbox 幂等集成测试 |
| 数据库从空库迁移和回滚通过 | PASS | PostgreSQL 18.6 上 Alembic `upgrade head`、`downgrade base` |
| 关键不变量有属性测试 | PASS | 金额、UTC、序列化和幂等键共 5 个 Hypothesis 属性测试 |

## 附加硬门

| 硬门 | 结果 | 说明 |
|---|---|---|
| P00 安全与供应链回归 | PASS | Bandit、秘密扫描、双生态依赖审计、SBOM、许可证与 Web 回归通过 |
| 真实 PostgreSQL，不使用 SQLite/Mock 冒充 | PASS | EDB PostgreSQL 18.6 loopback 一次性集群；归档 SHA-256 已固定 |
| P00/P01 追踪状态 | PASS | 466 条规范性要求完整，P00/P01 归属行均为 `verified` |
| `LIVE_TRADING` 锁 | PASS | 配置、代码、注册表、导入副作用和测试多重锁均通过 |
| 秘密与账户边界 | PASS | 0 明文秘密发现；未访问秘密存储或真实账户 |
| 阶段边界 | PASS | 未实现 P02 数据底座、Provider 接入或资产清点 |

## 验收统计

- 完整 CI：17/17 门通过；
- Python 3.13.15：90 passed，0 failed，0 skipped；
- Python 3.14.7：45 passed，0 failed，0 skipped；
- Web：2 个单元测试和 1 个 Chromium E2E 通过；
- 安全发现：0；已知 flake：0。

唯一非阻断警告是 Nautilus 回放触发的 pandas `Timestamp.utcnow` 弃用提示，已登记为
开放风险，不影响数值、事件哈希或回放确定性。
