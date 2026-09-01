# P03 ADR 引用

| ADR | 状态 | P03 适用决定 |
|---|---|---|
| `docs/adr/ADR-0001-runtime-and-version-policy.md` | Accepted | Python 3.13 正式基线、3.14 候选契约、精确依赖和实际契约优先 |
| `docs/adr/ADR-0002-event-engine-selection.md` | Accepted | NautilusTrader 保留确定性回放/兼容对象，不构成实盘批准 |
| `docs/adr/ADR-0003-live-lock.md` | Accepted | `LIVE_TRADING=false` 多重锁、无真实账户和订单能力 |
| `docs/adr/ADR-0004-p01-domain-and-postgresql-stack.md` | Accepted | P03 复用的领域事件、来源政策与持久化基础边界 |
| `docs/adr/ADR-0005-p02-columnar-data-foundation.md` | Accepted | 不可变数据湖、PIT、Silver schema、质量隔离和公开原始响应归档基础 |
| `docs/adr/ADR-0006-binance-public-market-data-contract.md` | Accepted for P03 implementation | Binance Spot/USDⓈ-M 官方公共 REST/WS 路由、网络依赖、限流和无认证边界 |
| `docs/adr/ADR-0007-p03-24h-soak-waiver.md` | Accepted | `P03-A01=waived`、阶段 `accepted_with_waiver`、禁止伪造 24 小时合格证据 |

ADR-0007 只豁免一个长时验收项，不 supersede ADR-0003 的实盘锁，也不降低任何安全、
来源、离线回放或其余 P03 门禁。外部版本和实际契约若变化，仍须以官方稳定文档与新契约
测试为准，并用新 ADR 记录。
