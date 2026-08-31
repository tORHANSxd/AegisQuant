# AegisQuant v3.1

个人 AI 加密资产多模态市场情报、预测、交易与可视化系统。当前仓库只完成
Phase P00 的规格固化、工程骨架、依赖契约与安全基线。

## 当前安全状态

- `LIVE_TRADING = false`
- `ORDER_SUBMISSION_ENABLED = false`
- 实盘适配器注册表为空
- 不连接交易账户，不收集任何凭据明文
- Web 骨架仅显示 `DEVELOPMENT / LIVE LOCKED`

## 本地验证

```text
uv sync --all-groups --frozen
uv run python scripts/ci.py
pnpm install --frozen-lockfile
pnpm verify
```

工程规格的冻结副本、需求矩阵、阶段状态与 P00 证据位于 `docs/spec/`、`state/`
和 `reports/phases/P00/`。任何后续工作只能由 `PROJECT_PHASE_STATE.yaml` 指定的
阶段启动；本次不包含 P01 工作。
