# AegisQuant 盈利导向重构 v4

当前最高优先级项目 SSOT 为
[`AegisQuant_盈利导向重构任务书_v4.md`](AegisQuant_盈利导向重构任务书_v4.md)。
研究目标为 AegisAlpha-CAT：低频 LONG/FLAT 趋势、经济过滤器、动态全成本门槛、波动率目标仓位
和严格滚动样本外验证。所有工作只使用 `main`；v5、v3.1 保留为历史实现和证据。

当前已开始 Phase A，冻结 60,480 行已有预测并复现所选组合指标。`50.0810%` 方向准确率对应
净复合收益 `+20.6379%` 的所选组合；`-38.8225%` 属于 `logistic_core` 候选。
候选完整逐样本预测未保存，因此 Phase A 状态为 `BLOCKED_MISSING_FAILED_PREDICTIONS`，
尚不能完成同预测失败归因或进入策略修改。详见
[`current_failure_report.md`](artifacts/alpha_v4/before/current_failure_report.md)。

## 当前安全状态

- `LIVE_TRADING = false`
- `ORDER_SUBMISSION_ENABLED = false`
- 实盘适配器注册表为空
- 不连接交易账户，不收集任何凭据明文
- Web 只读，fixture/synthetic/development 数据必须显示 EvidenceTier，且不得用于
  Alpha Promotion

## 本地验证

```text
.venv\Scripts\python.exe scripts/audit_current_failure.py --check
.venv\Scripts\python.exe -m pytest tests/alpha_v4 tests/research/test_public_market_backtest.py tests/p00
```

冻结工具只读取已存在的公开回测输出，不下载数据、不训练模型。`--check` 校验冻结工件的完整性，
成功不等于 Phase A 缺口已解决，更不代表存在可交易 Alpha。

历史 v5 验证命令保留：

```text
.venv\Scripts\python.exe -m scripts.generate_v5_p12_evidence --check
.venv\Scripts\python.exe scripts/ci.py --phase V5-P12
pnpm install --frozen-lockfile
pnpm verify
```

历史 CI 只验证 `DEVELOPMENT` 契约与回归门禁，不代表真实 30 日 Forward、真实 Binance Testnet、
外部告警或 Canary 授权；当前七项硬门均为 `BLOCKED_EXTERNAL_INPUT`。即便未来生成
`CANARY_REVIEW_READY`，也只允许人工复核，不能自动解锁资金、订单或 Live。

## 真实公开市场验证

```text
.venv\Scripts\python.exe scripts/run_real_market_backtest.py --check
```

原流程从 Binance 官方公开 REST 端点获取 BTCUSDT、ETHUSDT 小时线，保存逐页响应哈希，排除触及
交易所数据缺口的样本，以滚动训练/验证/校准/测试和下一根 K 线执行规则生成开发期 OOS 证据。
摘要位于 `reports/v5/REAL_DATA_BACKTEST/BACKTEST_REPORT.md`；原始与逐行 OOS 数据按 `.gitignore`
留在本机，版本化报告保存其内容哈希。此流程不打开最终盲测集，也没有 Promotion 权限。

当前状态位于 `state/ALPHA_V4_PROJECT_STATE.yaml`，规格索引位于 `state/SPEC_INDEX.md`。
`state/V5_PROJECT_STATE.yaml`、`reports/v5/`、`state/PROJECT_PHASE_STATE.yaml`、
`reports/phases/` 和旧规格仅保留历史含义。Phase A 期间不得运行会重训原模型的历史生成命令。
