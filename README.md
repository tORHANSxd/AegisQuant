# AegisQuant 盈利导向重构 v4

当前最高优先级项目 SSOT 为
[`AegisQuant_盈利导向重构任务书_v4.md`](AegisQuant_盈利导向重构任务书_v4.md)。
研究目标为 AegisAlpha-CAT：低频 LONG/FLAT 趋势、经济过滤器、动态全成本门槛、波动率目标仓位
和严格滚动样本外验证。所有工作只使用 `main`；v5、v3.1 保留为历史实现和证据。

Phase A 已冻结 60,480 行已有预测并复现所选组合指标。`50.0810%` 方向准确率对应
净复合收益 `+20.6379%` 的所选组合；`-38.8225%` 属于 `logistic_core` 候选。
用户已明确允许重建缺失的旧候选预测并保留来源标记；重建结果位于
[`reconstruction_manifest.json`](artifacts/alpha_v4/reconstructed_before/reconstruction_manifest.json)，
标记为 `RECONSTRUCTED_BASELINE`，与原候选指标的差异小于 `1e-12`。原始冻结报告保留当时的缺口记录。
本轮实现、开发期验证和报告已完成，结论为 **NO_PROVEN_ALPHA**，维持空仓。
14 折中透明趋势 B3 累计净收益 `+102.69%`，但仅 `6/14` 折盈利，最大回撤 `42.47%`，
未通过统计和稳定性门槛。动态门槛 B4 全程空仓；XGBoost 完整版本 B7 为 `-1.51%`。
ML 未获生产准入，资金费组合未获独立准入；没有可用的、此前未使用的连续 12 个月最终留出集，访问次数为 0。
具体数字、成本压力限制及任务书要求的 12 项回答见
[`最终结论`](artifacts/alpha_v4/reports/final_go_no_go.md)。

## 当前安全状态

- `LIVE_TRADING = false`
- `ORDER_SUBMISSION_ENABLED = false`
- 实盘适配器注册表为空
- 不连接交易账户，不收集任何凭据明文
- Web 只读，fixture/synthetic/development 数据必须显示 EvidenceTier，且不得用于
  Alpha Promotion

## 本地验证

```text
.venv\Scripts\python.exe -m scripts.audit_current_failure --check
.venv\Scripts\python.exe -m scripts.reconstruct_alpha_v4_baseline --check
.venv\Scripts\python.exe -m scripts.run_alpha_v4_walkforward --check
.venv\Scripts\python.exe -m scripts.run_alpha_v4_final_holdout --check
.venv\Scripts\python.exe -m scripts.audit_alpha_v4_carry --check
.venv\Scripts\python.exe -m scripts.finalize_alpha_v4_evidence --check
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m pyright
```

上述 `--check` 只校验已存在工件，不重新拟合模型或访问最终留出集。
成功只说明证据完整性，不代表存在可交易 Alpha。

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
`reports/phases/` 和旧规格仅保留历史含义。旧基线的授权重建结果与原始冻结证据分开保存；
不得覆盖原始产物或把重建结果冒充原始预测。
