# P01 ADR 引用

| ADR | 状态 | P01 适用决定 |
|---|---|---|
| `docs/adr/ADR-0001-runtime-and-version-policy.md` | Accepted | Python 3.13 正式基线、3.14 候选契约、精确直依赖与锁文件策略 |
| `docs/adr/ADR-0002-event-engine-selection.md` | Accepted | NautilusTrader 仅用于确定性事件回放，Beta 状态不得解读为实盘批准 |
| `docs/adr/ADR-0003-live-lock.md` | Accepted | `LIVE_TRADING=false` 多重锁、无 Live Adapter、无真实账户访问 |
| `docs/adr/ADR-0004-p01-domain-and-postgresql-stack.md` | Accepted | Pydantic 2.13.5、SQLAlchemy 2.0.52、Alembic 1.19.1、Psycopg 3.3.4、PostgreSQL 18.6 及真实契约测试 |

P01 未新增其他隐含架构决定。PostgreSQL 分发来源、loopback trust 测试边界和 schema
确定性生成均由 ADR-0004 明确记录；后续若改变任一项，必须通过新 ADR supersede，
不得原地改写历史决定。
