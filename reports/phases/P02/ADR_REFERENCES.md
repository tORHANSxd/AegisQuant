# P02 ADR 引用

| ADR | 状态 | P02 适用决定 |
|---|---|---|
| `docs/adr/ADR-0001-runtime-and-version-policy.md` | Accepted | Python 3.13 正式基线、3.14 候选契约、精确直依赖与锁文件策略 |
| `docs/adr/ADR-0002-event-engine-selection.md` | Accepted | NautilusTrader 仅保留确定性回放契约，不构成实盘能力或批准 |
| `docs/adr/ADR-0003-live-lock.md` | Accepted | `LIVE_TRADING=false` 多重锁、无 Live Adapter、无真实账户访问 |
| `docs/adr/ADR-0004-p01-domain-and-postgresql-stack.md` | Accepted | P02 复用的领域、事件、来源政策与 PostgreSQL 基础契约 |
| `docs/adr/ADR-0005-p02-columnar-data-foundation.md` | Accepted | 列式依赖、DuckDB 安全边界、类型适配、AES-GCM archive、固定公开样本和合成扫描边界 |

P02 未隐含批准任何交易所 Provider、网络扩展、真实用户路径、云存储或 Live 能力。依赖
版本或实际兼容性若变化，必须先用官方稳定文档与契约测试验证，并通过新 ADR supersede，
不得原地篡改历史决定。
