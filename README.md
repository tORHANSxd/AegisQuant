# AegisQuant v5.0

个人 AI 加密资产事实核验、因果预测、量化研究、交易与可视化系统。当前 SSOT 为
`AegisQuant_v5.0_Truth_Causal_AI_Forecast_Codex_Master_Plan.md`，实施阶段为
`V5-P12`（Testnet / Canary Readiness）。既有 v3.1 实现和报告保留为历史开发基线，不自动升级为
v5 Alpha 证据；P12 已建立 Truth、Forecast、Cost、Paper、Shadow、Testnet、Risk 七项不可加权
硬门，以及 Testnet、外部告警、签名授权和对账收据。当前指标仍为
`DEVELOPMENT` 合约夹具；另有隔离的真实公开市场 OOS 验证，但不冒充因果效应、Forward 证据或
可交易 Alpha。

## 当前安全状态

- `LIVE_TRADING = false`
- `ORDER_SUBMISSION_ENABLED = false`
- 实盘适配器注册表为空
- 不连接交易账户，不收集任何凭据明文
- Web 只读，fixture/synthetic/development 数据必须显示 EvidenceTier，且不得用于
  Alpha Promotion

## 本地验证

```text
.venv\Scripts\python.exe -m scripts.generate_v5_p12_evidence --check
.venv\Scripts\python.exe scripts/ci.py --phase V5-P12
pnpm install --frozen-lockfile
pnpm verify
```

上述 CI 只验证 `DEVELOPMENT` 契约与回归门禁，不代表真实 30 日 Forward、真实 Binance Testnet、
外部告警或 Canary 授权；当前七项硬门均为 `BLOCKED_EXTERNAL_INPUT`。即便未来生成
`CANARY_REVIEW_READY`，也只允许人工复核，不能自动解锁资金、订单或 Live。

## 真实公开市场验证

```text
.venv\Scripts\python.exe scripts/run_real_market_backtest.py
.venv\Scripts\python.exe scripts/run_real_market_backtest.py --check
```

该流程从 Binance 官方公开 REST 端点获取 BTCUSDT、ETHUSDT 小时线，保存逐页响应哈希，排除触及
交易所数据缺口的样本，以滚动训练/验证/校准/测试和下一根 K 线执行规则生成开发期 OOS 证据。
摘要位于 `reports/v5/REAL_DATA_BACKTEST/BACKTEST_REPORT.md`；原始与逐行 OOS 数据按 `.gitignore`
留在本机，版本化报告保存其内容哈希。此流程不打开最终盲测集，也没有 Promotion 权限。

v5 状态位于 `state/V5_PROJECT_STATE.yaml`，阶段证据位于 `reports/v5/`。旧
`state/PROJECT_PHASE_STATE.yaml`、`reports/phases/` 和 v3.1 规格仅保留历史含义。
