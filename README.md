# AegisQuant v3.1

个人 AI 加密资产多模态市场情报、预测、交易与可视化系统。当前仓库完成
Phase P00 安全基线，并正在验收 Phase P01 的纯领域核心、事件契约和 PostgreSQL
持久化骨架。

## 当前安全状态

- `LIVE_TRADING = false`
- `ORDER_SUBMISSION_ENABLED = false`
- 实盘适配器注册表为空
- 不连接交易账户，不收集任何凭据明文
- Web 骨架仅显示 `DEVELOPMENT / LIVE LOCKED`

## 本地验证

```text
uv sync --all-groups --frozen
uv run python scripts/setup_postgres.py
uv run python scripts/ci.py
pnpm install --frozen-lockfile
pnpm verify
```

工程规格的冻结副本、需求矩阵与阶段状态位于 `docs/spec/` 和 `state/`；阶段证据
分别位于 `reports/phases/P00/` 与 `reports/phases/P01/`。P01 不包含数据接入、
真实账户连接、订单发送或任何 P02 实现。
