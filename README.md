# AegisQuant v3.1

个人 AI 加密资产多模态市场情报、预测、交易与可视化系统。当前仓库已接受
Phase P00/P01，并正在验收 Phase P02 的不可变 Parquet 数据湖、Provider Registry、
point-in-time 数据语义、只读资产扫描与本地查询底座。

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
位于 `reports/phases/P00/`、`P01/` 与 `P02/`，数据证据位于 `reports/data/`。
P02 没有扫描真实用户路径，也不包含真实账户连接、订单发送或任何 P03 实现。
