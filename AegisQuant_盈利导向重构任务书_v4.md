# AegisQuant 盈利导向重构任务书 v4

> 目标项目：`https://github.com/tORHANSxd/AegisQuant`  
> 编制日期：2026-09-03  
> 执行对象：本地 Codex / GPT-5.6 Codex  
> 当前已知失败结果：未来收益方向/曲线方向成功率约 50%，历史模拟净亏损不到 40%  
> 项目状态：**仅研究、回测与模拟；必须继续锁死实盘交易**

---

## 0. 最终技术决策

本任务不复制任何 GitHub 项目宣传的收益率，也不承诺改完后一定盈利。公开代码能够证明的通常只是“作者在某个数据区间得到过正回测”，不能证明迁移到 AegisQuant、其他时间段或真实交易环境后仍然盈利。

经过案例筛选，采用以下组合，而不是单纯更换预测模型：

> **AegisAlpha-CAT：低频趋势候选信号 + XGBoost/LightGBM 经济过滤器 + 动态全成本交易门槛 + 波动率目标仓位 + 严格滚动样本外验证。**

第一阶段只允许 `LONG/FLAT`，禁止做空和直接多空反手。第二阶段再独立研究现货—永续资金费/基差中性套利。新闻、推文和多模态 AI 在没有独立证明增量收益前，只能作为风险否决或减仓因子，不能直接开仓。

本方案被选中的原因：

1. AegisQuant 当前最直接的问题不是“模型不够复杂”，而是微小正负预测可被机械映射为 `+1/-1` 仓位，接近随机的信号会产生极高换手。
2. 2026 年一项使用约 7 万条 BTC/USDT 小时数据和 27 个滚动样本外折的研究，报告朴素符号交易在 10 bps 成本下从毛盈利变为严重亏损；加入成本门槛后，XGBoost 多头策略的交易次数从 10,619 次降到 251 次，并在其样本中恢复正收益。这与当前 AegisQuant 的失败模式高度相似。
3. `Globe-Research/bittrends` 的公开 GitHub 代码和配套研究提示，加密资产的趋势优势更可能存在于多日尺度，而非每根小时 K 线反复猜涨跌；但其成本假设过于乐观，因此只借鉴“低频趋势结构”，不复制收益数字和最优参数。
4. 另一个公开 GitHub 研究 `ITheClixs/crypto-return-predictability` 对 2020—2026 年 BTC、ETH、SOL 做严格 purged walk-forward 后，没有发现可交易的短周期方向预测优势，并指出许多高 Sharpe 结果只是长期持有敞口。这说明必须把模型与简单趋势、长期持有和空仓基线逐项比较。
5. AegisQuant 已经包含 CatBoost、LightGBM、XGBoost、Optuna、概率预测、组合优化和多模态模块，不需要推倒重建；应先修复经济语义，再把现有组件接入正确的预测—交易转换链路。

### 0.1 “最能盈利”的定义

本项目中的“最能盈利”统一定义为：

```text
在冻结的样本外数据、真实全成本、无前视偏差和受控回撤条件下，
最大化可复合的净资产增长，而不是最大化训练集准确率或单一区间 CAGR。
```

模型选择目标不得是单一 MSE、accuracy 或训练期收益。研究层的默认目标应接近：

```text
robust_score =
    median_walkforward_log_growth
    - drawdown_penalty
    - CVaR_penalty
    - turnover_cost_penalty
    - fold_instability_penalty
    - multiple_testing_penalty
```

---

## 1. 必须保留的安全约束

以下状态不得修改：

```text
LIVE_TRADING = false
ORDER_SUBMISSION_ENABLED = false
实盘适配器注册表为空
不得读取或要求真实 API 私钥
```

任何阶段不得通过提高杠杆掩盖负期望，不得把回测账户连接到真实交易账户。

建立工作分支：

```bash
git switch -c research/aegis-alpha-v4-cost-aware
```

第一笔提交只允许保存当前失败运行证据，不得修改策略。

---

## 2. Phase A：冻结并复现当前失败结果

### 2.1 查明两个用户看到的指标

必须精确定位：

- “曲线预测成功率约 50%”对应哪个字段；
- “亏损不到 40%”对应算术收益、复合净值收益还是账户权益变化；
- 使用的是 research evaluator、vector backtest 还是 event backtest；
- 预测目标是下一根收益、固定 horizon 累计收益、价格水平还是整段路径；
- 特征时间、决策时间、最早可成交时间、目标起止时间分别是什么。

生成：

```text
artifacts/alpha_v4/before/run_manifest.json
artifacts/alpha_v4/before/metric_lineage.json
artifacts/alpha_v4/before/resolved_config.yaml
artifacts/alpha_v4/before/current_failure_report.md
```

`run_manifest.json` 至少包含：

```text
git_commit_sha
python_version
lockfile_sha256
dataset_paths
dataset_sha256
venue
instrument_id
instrument_type
timeframe
start_time
end_time
warmup_range
prediction_horizon
execution_delay
initial_equity
final_equity
arithmetic_return
compounded_return
reported_accuracy_name
reported_accuracy_formula
fee_schedule_version
spread_model
slippage_model
impact_model
funding_model
borrow_model
leverage
position_mode
random_seeds
```

### 2.2 冻结当前预测，不允许重新训练

保存：

```text
artifacts/alpha_v4/before/frozen_predictions.parquet
```

字段：

```text
sample_id
instrument_id
feature_time
decision_time
earliest_execution_time
target_start_time
target_end_time
prediction_raw
prediction_direction
prediction_confidence
realized_return
realized_direction
current_position
target_position
order_quantity
```

先用完全相同预测序列做后续归因，避免把“修复回测器”和“重新训练模型”混为一谈。

### 2.3 强制执行失败归因矩阵

在不重新训练模型的条件下运行：

| 编号 | 实验 | 目的 |
|---|---|---|
| A0 | 原始代码、原始配置 | 固定失败基准 |
| A1 | 修复后的回测器、相同预测 | 测量回测缺陷影响 |
| A2 | A1 且全部交易成本为零 | 判断信号是否有毛优势 |
| A3 | A1 且只做多，负预测为空仓 | 判断做空端是否拖累 |
| A4 | A1 且只做空，正预测为空仓 | 独立检验做空 |
| A5 | 预测整体取反 | 排查标签或下单符号错误 |
| A6 | 预测相对目标收益偏移 `-2,-1,0,+1,+2` 根 K 线 | 排查时间错位 |
| A7 | 仅交易预测绝对值最高的 50%、30%、20%、10%、5% | 检查高置信度子集 |
| A8 | 保持相同换手、持仓期和多空比例的 1,000 个随机策略 | 判断是否优于随机 |
| A9 | 永久空仓 | 最低经济基线 |
| A10 | 同期买入并持有 | 识别伪装成预测能力的长期敞口 |

输出：

```text
artifacts/alpha_v4/diagnostics/failure_attribution.parquet
artifacts/alpha_v4/diagnostics/shift_scan.parquet
artifacts/alpha_v4/diagnostics/confidence_buckets.parquet
artifacts/alpha_v4/diagnostics/random_baseline.parquet
artifacts/alpha_v4/diagnostics/cost_waterfall.json
artifacts/alpha_v4/diagnostics/failure_attribution.md
```

判定规则：

```text
A2 仍为负：当前预测不存在可见毛优势，禁止只调交易参数救模型。
A5 显著优于 A1：标记 POSSIBLE_LABEL_OR_ORDER_SIGN_FAILURE，查明根因，禁止直接把信号反转上线。
最佳 shift != 0：标记 TARGET_EXECUTION_ALIGNMENT_FAILURE。
A3 明显优于 A1、A4 为负：默认改为 LONG/FLAT，做空保持禁用。
只有最高置信度子集为正：允许开发弃权/过滤器，但阈值只能在训练和验证段确定。
未优于匹配换手随机策略：标记 NO_DEMONSTRATED_PREDICTIVE_EDGE。
```

---

## 3. Phase B：先修复回测和标签，再谈盈利

以下是 P0 阻断项。任一未完成，不允许进行超参数优化。

### 3.1 修复方向标签的成本不对称

当前 `src/aegisquant/labels/generators.py` 中存在：

```python
net = gross - cost.total_rate
flat_band = abs(cost.total_rate) + risk_flat_threshold

if net > flat_band:
    UP
elif net < -flat_band:
    DOWN
```

在成本 `c > 0`、风险阈值 `r >= 0` 时等价于：

```text
UP:   gross > 2c + r
DOWN: gross < -r
```

这会系统性偏向 DOWN 标签。删除该分类方式，改为动作价值标签。

新增模型：

```python
class ActionValueLabel(DomainModel):
    decision_time: UtcDateTime
    earliest_execution_time: UtcDateTime
    horizon_end_time: UtcDateTime
    gross_long_return: Decimal
    gross_short_return: Decimal
    long_entry_cost: Decimal
    long_exit_cost: Decimal
    short_entry_cost: Decimal
    short_exit_cost: Decimal
    expected_funding_long: Decimal
    expected_funding_short: Decimal
    expected_borrow_short: Decimal
    net_value_long: Decimal
    net_value_flat: Decimal
    net_value_short: Decimal
    best_action: DirectionClass
    action_margin: Decimal
```

动作价值：

```text
V_long  = long_gross_return
          - long_entry_cost
          - long_exit_cost
          - long_funding
          - long_risk_buffer

V_short = short_gross_return
          - short_entry_cost
          - short_exit_cost
          - short_funding
          - short_borrow
          - short_tail_risk_buffer

V_flat  = 0
```

只有：

```text
max(V_long, V_short) - V_flat
> uncertainty_buffer + minimum_economic_margin
```

才产生非 FLAT 标签。多头、空头必须分别计算；资金费必须保留方向符号。

修改：

```text
src/aegisquant/labels/models.py
src/aegisquant/labels/generators.py
```

新增测试：

```text
tests/unit/labels/test_action_value_symmetry.py
tests/unit/labels/test_directional_costs.py
tests/unit/labels/test_executable_entry_time.py
tests/unit/labels/test_funding_sign.py
```

### 3.2 Vector 回测必须处理全部行情事件

当前 `src/aegisquant/backtest/vector.py` 只保留与订单到达时间对齐的 `selected_bars`，会删除没有新订单的中间 K 线。

必须改成：

```python
return self.event_engine.run(
    ...,
    market_events=bar_values,
    orders=order_values,
)
```

向量层只负责批量计算信号和订单对齐，不能删掉持仓路径。

新增测试：

```text
tests/unit/backtest/test_vector_replays_all_bars.py
tests/unit/backtest/test_final_bar_valuation.py
tests/unit/backtest/test_vector_event_sparse_order_parity.py
```

### 3.3 每个市场事件都做 Mark-to-Market

当前权益点主要在成交、资金费和结束时写入，风险指标依赖成交频率。改为：

1. 每个市场事件更新 mark；
2. 处理该时间点的取消、故障、成交和资金费；
3. 同时间戳事件完成后只写入一个聚合权益点；
4. 固定频率重采样后计算 Sharpe、Sortino、回撤。

权益恒等式：

```text
equity =
    cash
    + spot_market_value
    + derivative_unrealized_pnl
    - accrued_funding
    - accrued_borrow_interest
    - unpaid_fees
    - liquidation_penalties
```

必须同时报告：

```text
mark_to_market_final_equity
forced_close_final_equity
```

`forced_close_final_equity` 必须模拟退出并扣除完整退出成本。

修改：

```text
src/aegisquant/backtest/engine.py
src/aegisquant/backtest/metrics.py
src/aegisquant/backtest/models.py
```

### 3.4 接通保证金、强平、借币和 reduce-only

必须在主事件引擎中实现：

- 下单前初始保证金和余额检查；
- 每个 mark 后维持保证金检查；
- 自动强平和强平罚金；
- 空头借币成本与借币上限；
- 现货余额不足时拒单；
- `reduce_only` 订单只能减少仓位，超量部分裁剪，空仓时拒绝；
- 止损/止盈 OCO 互斥；
- 同一 K 线同时触及 TP/SL 时采用预先声明的保守规则，或下钻更细粒度数据，禁止两张退出单都成交。

修改：

```text
src/aegisquant/backtest/engine.py
src/aegisquant/backtest/margin.py
src/aegisquant/backtest/fills.py
src/aegisquant/backtest/rules.py
src/aegisquant/backtest/models.py
```

### 3.5 修复研究评估指标

当前 `evaluate_predictions()` 默认 `edge_threshold=0`，任何微小非零预测都会变为满仓 `+1/-1`，且 `gross_return/net_return` 为算术求和。

要求：

- 删除生产可用路径中的默认零阈值；未提供经过校准的门槛时返回 `NO_TRADE`；
- 复合净值逐期计算；
- 计入最终退出成本；
- `direction_accuracy` 只作为预测诊断，不再称为“曲线成功率”；
- FLAT、LONG、SHORT 分开统计；
- 交易胜率必须按完整 round-trip 交易计算；
- 风险收益指标使用固定频率 MTM 权益序列。

分别输出：

```text
预测层：MSE, MAE, R2_OS, Pearson IC, Spearman IC,
       balanced accuracy, macro F1, MCC, Brier, calibration error,
       abstention coverage, Pesaran–Timmermann sign test

交易层：closed trade count, win rate, average win, average loss,
       payoff ratio, expectancy, holding time, turnover, reversal count

账户层：compounded gross return, compounded net return, CAGR,
       max drawdown, drawdown duration, Sharpe, Sortino, Calmar,
       CVaR, cost/gross-profit ratio, final MTM equity, forced-close equity
```

修改：

```text
src/aegisquant/research/models/baselines.py
src/aegisquant/backtest/metrics.py
```

### 3.6 模型委员会必须允许“没有可交易优势”

当前委员会不能被迫从一组亏损模型中选一个。

增加：

```python
class CouncilDecision(StrEnum):
    SELECTED = "SELECTED"
    NO_PROVEN_ALPHA = "NO_PROVEN_ALPHA"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    REJECTED_FOR_INSTABILITY = "REJECTED_FOR_INSTABILITY"
```

`selected_model_id` 改为可空。只有同时通过统计、经济、成本压力和稳定性门槛，才允许选中模型；否则组合目标仓位为当前仓位或零，禁止新开仓。

修改：

```text
src/aegisquant/research/council.py
src/aegisquant/research/reports/*
```

---

## 4. Phase C：实现 AegisAlpha-CAT 策略

## 4.1 第一阶段交易范围

默认研究范围：

```text
资产：BTCUSDT
决策频率：4h
风险状态频率：1d
执行：决策 K 线完全结束后，下一可执行事件
模式：LONG/FLAT
最大总敞口：1.0 NAV
杠杆：不得超过 1x
固定止盈：禁用
灾难止损：仅作为风险熔断，不用于参数挖掘
```

若同时有现货和永续数据：

- 分别做独立回测；
- 不允许观察最终测试集后选择市场；
- 默认先以现货 LONG/FLAT 验证信号，避免资金费和强平实现缺陷；
- 永续只允许 1x 名义敞口，且必须通过完整资金费和保证金测试。

暂不扩展到大量山寨币，避免幸存者偏差、下架偏差和流动性偏差。BTC 通过后，第二阶段只增加 ETH；SOL 等资产必须使用 point-in-time 可交易资产清单。

## 4.2 透明趋势候选信号

趋势模块的目的不是直接宣称盈利，而是生成低换手、可解释的候选方向，让模型只负责筛掉质量差的候选交易。

新增：

```text
src/aegisquant/research/strategies/__init__.py
src/aegisquant/research/strategies/cost_aware_trend.py
```

默认中心参数来源于公开趋势研究中的多日尺度：

```text
fast_window = 10 天
slow_window = 40 天
```

4h 数据对应：

```text
fast_bars = 60
slow_bars = 240
```

只允许在训练/验证阶段检查小范围稳定邻域：

```text
fast_days ∈ {7, 10, 14}
slow_days ∈ {30, 40, 60}
```

不得从数百个窗口中选择单个最优点。要求最佳区域在相邻参数上仍然为正；若只有一个孤立参数盈利，判定为过拟合。

构建连续趋势分数，不直接用二元交叉：

```text
ma_distance   = log(EMA_fast / EMA_slow) / NATR
mom_10d       = log(close_t / close_t-10d) / vol_10d
mom_40d       = log(close_t / close_t-40d) / vol_40d
breakout      = normalized distance to trailing 20d high/low
trend_score   = robust_equal_weight(ma_distance, mom_10d, mom_40d, breakout)
```

所有特征先在训练窗口内 winsorize/scale；验证和测试只能使用训练窗口拟合的变换器。推荐使用中位数与 MAD，而不是全样本标准化。

候选状态必须带滞回：

```text
FLAT -> LONG：trend_score > entry_threshold 且满足最少连续确认
LONG -> FLAT：trend_score < exit_threshold
entry_threshold > exit_threshold
```

中心方案不设置固定止盈，让趋势盈利继续运行。灾难性退出可使用宽幅 ATR 风险规则，但只能在预先声明的小范围内验证，不能对最终测试集调优。

## 4.3 特征集：少而稳定，禁止“指标堆砌”

修改：

```text
src/aegisquant/features/market.py
src/aegisquant/features/models.py
src/aegisquant/features/registry.py
```

第一版最多允许以下特征组：

```text
收益/趋势：1bar, 6bar, 30bar, 60bar, 240bar log return
趋势结构：fast/slow MA ratio, price/slow MA distance, Donchian state
波动：ATR/NATR, realized vol 6/42/180 bars, downside semivariance
成交量：log-volume z-score, turnover change, Amihud proxy
交易成本：bid-ask spread, quoted depth, estimated impact, recent slippage
永续特征：funding level, funding change, rolling funding sum, spot-perp basis
状态：volatility regime, liquidity regime, weekend/session flags
质量：stale flag, missingness flags, source latency, data-quality score
```

禁止：

- 使用未来区间的最高/最低价构造当前特征；
- 对完整样本统一归一化；
- 用当前未收盘 K 线的最终 OHLCV；
- 一次加入数百个高度相关技术指标；
- 在最终测试集上按 SHAP 或 feature importance 反向选特征。

事件、新闻、推文特征第一阶段不参与开仓，只能作为独立风险覆盖层，见 Phase G。

## 4.4 预测目标：预测经济价值，不预测价格曲线外观

不再把“预测价格曲线方向”作为最终交易目标。主目标应是：

```text
从最早可执行入场价开始，在未来 h 期持有 LONG 相对 FLAT 的可实现收益。
```

第一版 horizon：

```text
h ∈ {6, 12} 个 4h bar，即 24h 或 48h
```

只能在训练/验证段选择一个 horizon；最终测试段冻结。

标签：

```text
gross_forward_return =
    log(executable_exit_price[t+h] / executable_entry_price[t+1])

net_opportunity =
    gross_forward_return
    - expected_entry_cost_at_t
    - expected_exit_cost_at_t
    - expected_holding_cost_at_t
```

注意：模型可以预测毛收益分布；交易决策必须使用决策时刻可估计的成本。不得把未来真实滑点直接作为当时已知特征。

## 4.5 树模型作为经济过滤器，而不是直接翻多翻空

优先级：

```text
1. XGBoost
2. LightGBM challenger
3. 线性/ElasticNet 基线
4. 深度模型只在前三者通过后作为 challenger
```

AegisQuant 已有相应依赖，不新增不必要框架。

新增或修改：

```text
src/aegisquant/research/models/tree.py
src/aegisquant/research/models/probabilistic.py
src/aegisquant/research/models/uncertainty.py
src/aegisquant/research/models/economic_gate.py
```

模型应输出：

```text
expected_gross_return
q10_return
q50_return
q90_return
p_net_positive
prediction_uncertainty
calibration_status
```

推荐两条并行基线：

1. 回归：预测未来 24h/48h 毛收益；
2. Meta-label：只对趋势候选开仓点预测“扣除完整往返成本后是否为正”。

Meta-label 的 primary signal 必须来自趋势模块，模型不得自行生成任意方向仓位。

概率使用时间序列内部校准：

```text
训练段拟合模型
验证段拟合 isotonic 或 Platt calibration
测试段只推理
```

不得在测试折重新校准。

## 4.6 核心：动态全成本经济门槛

新增：

```text
src/aegisquant/portfolio/economic_gate.py
src/aegisquant/portfolio/transition_costs.py
```

每个决策时刻估计完整转仓成本：

```text
entry_cost =
    taker_or_maker_fee
    + entry_half_spread
    + expected_entry_slippage
    + expected_entry_impact
    + latency_adverse_selection

exit_cost =
    expected_exit_fee
    + expected_exit_half_spread
    + expected_exit_slippage
    + expected_exit_impact

holding_cost =
    expected_directional_funding
    + expected_borrow_interest
    + settlement_cost

round_trip_cost = entry_cost + exit_cost + holding_cost
```

不得用一个固定 `no_trade_zone` 代替时间变化的经济门槛。

对 LONG/FLAT 第一阶段，使用动作价值：

```text
Q_long =
    conservative_expected_return
    - expected_holding_cost
    - downside_risk_penalty

Q_flat = 0

conservative_expected_return 可取：
    q50 - uncertainty_weight * (q90 - q10)
或经过校准的下置信界。
```

转换门槛：

```text
transition_hurdle(current -> action) =
    lambda_cost * estimated_transition_cost
    + model_uncertainty_buffer
    + execution_uncertainty_buffer
```

进入 LONG：

```text
trend_candidate == LONG
AND p_net_positive >= p_enter
AND Q_long - Q_flat > lambda_cost * round_trip_cost
AND data_quality_passed
AND risk_state_allows_entry
```

退出 LONG：

```text
Q_flat - Q_hold_long > lambda_cost * exit_cost
OR trend_exit_confirmed
OR hard_risk_veto
```

否则保持当前仓位。不能因为预测值从 `+0.00001` 变为 `-0.00001` 就完整反手。

`lambda_cost` 只允许：

```text
{1.5, 2.0, 2.5}
```

中心值为 `2.0`。只能在每个 walk-forward 折的验证段选择；若三者差异不稳定，固定使用 2.0。禁止扩展为大规模阈值搜索。

## 4.7 目标仓位和换手控制

修改：

```text
src/aegisquant/portfolio/models.py
src/aegisquant/portfolio/optimizer.py
```

当前固定原始分数 no-trade zone 改为经济门槛后，再进行仓位计算：

```text
vol_scale = min(1, target_volatility / forecast_realized_volatility)

confidence_scale = clip(
    (p_net_positive - p_enter) / (p_full_size - p_enter),
    0,
    1,
)

raw_target_weight =
    LONG_indicator * vol_scale * confidence_scale

final_target_weight = min(raw_target_weight, maximum_weight)
```

默认硬约束：

```text
maximum_weight = 1.0
maximum_gross_weight = 1.0
maximum_leverage = 1.0
short_weight = 0
```

目标波动率只允许一个小型预注册集合，例如：

```text
{15%, 20%, 25% annualized}
```

由验证段选择，并检查相邻值稳定性。

订单差额必须考虑未完成订单：

```text
desired_delta =
    target_quantity
    - current_quantity
    - signed_pending_quantity
```

增加最小经济调仓量：小于交易所最小名义金额、精度约束或成本门槛的 delta 不下单。

禁止直接：

```text
LONG -> SHORT
SHORT -> LONG
```

未来启用做空时也必须：

```text
LONG -> FLAT -> 连续确认 -> SHORT
```

## 4.8 风险控制原则

风险模块的目的不是把负期望变成正期望，而是防止尾部事故。

第一阶段：

- 不使用固定百分比止盈；
- 使用趋势/经济价值退出；
- 可设置宽幅灾难止损或风险熔断；
- 高波动、流动性恶化、数据陈旧时降低仓位；
- 组合回撤达到预设阈值后只允许减仓；
- 恢复必须经过冷却期和数据质量确认；
- 风险参数不得通过最终测试收益优化。

任何策略只有在无风险覆盖层时先显示正毛期望，才允许加风险覆盖层。

---

## 5. Phase D：Walk-forward 和防过拟合协议

## 5.1 时间切分

第一版采用与近期成本感知 BTC 研究相近的滚动设计：

```text
训练：12 个月
验证：3 个月
测试：3 个月
步长：3 个月
```

若最慢特征需要更长历史，可将训练窗口增加到 18 或 24 个月，但必须在读取最终 holdout 前冻结。

每折执行：

```text
train -> fit scaler/features/model
validation -> choose limited hyperparameters, calibration, lambda_cost
purge -> 至少覆盖最大标签 horizon
embargo -> 至少 1 个完整决策 bar，并根据重叠标签扩大
then test -> exactly once
```

## 5.2 最终封存集

把数据末端至少 12 个月设为 final holdout：

```text
artifacts/alpha_v4/holdout/frozen_holdout_manifest.json
artifacts/alpha_v4/holdout/holdout_access_log.jsonl
```

在以下内容冻结之前禁止读取最终 holdout：

- 特征清单；
- 候选趋势公式；
- 模型家族；
- horizon；
- 成本倍率集合；
- `lambda_cost` 集合；
- 仓位和风险规则；
- 通过/失败门槛。

最终 holdout 只能正式运行一次。代码缺陷导致无法运行时可以修复，但必须记录变更和理由，禁止根据收益结果修改策略再重复读取。

## 5.3 多重检验预算

每个研究程序都要记录：

```text
number_of_features_tried
number_of_horizons_tried
number_of_model_families_tried
number_of_hyperparameter_trials
number_of_cost_thresholds_tried
number_of_risk_rules_tried
```

使用：

```text
Deflated Sharpe Ratio
Probability of Backtest Overfitting
block bootstrap confidence intervals
White Reality Check 或 SPA（适用时）
FDR/Holm correction（多策略比较时）
```

Optuna 不能无限搜索；每折每模型设硬 trial budget，并保存全部失败 trial，不得只保留最优结果。

---

## 6. Phase E：逐层消融，只有增量有效才保留

必须按以下顺序运行，禁止直接报告最终复杂模型：

| 层级 | 策略 | 说明 |
|---|---|---|
| B0 | Cash | 永久空仓 |
| B1 | Buy & Hold | 同期长期敞口基准 |
| B2 | 修复后的旧模型 | 相同冻结预测 |
| B3 | 10/40 天 LONG/FLAT 趋势 | 无 ML、真实成本 |
| B4 | B3 + 动态成本门槛 | 检验换手控制贡献 |
| B5 | B4 + XGBoost 经济过滤器 | 检验 ML 的增量价值 |
| B6 | B5 + 概率校准/不确定性 | 检验置信边界贡献 |
| B7 | B6 + 波动率目标仓位 | 检验风险调整贡献 |
| B8 | 独立 funding/basis sleeve | 第二阶段，禁止提前混合 |
| B9 | 通过后的 B7/B8 组合 | 仅两者各自通过后运行 |

每个增量必须报告：

```text
Δ compounded net return
Δ Sharpe
Δ Calmar
Δ max drawdown
Δ turnover
Δ total cost
Δ trade count
bootstrap CI of return difference
fold-by-fold win/loss
```

保留规则：

```text
如果 B5 不能在多个折中稳定优于 B4，则删除 ML 生产路径，保留简单趋势 + 成本门槛。
如果 B4 不能优于 B3，则经济门槛实现或预测幅度校准存在问题。
如果 B3 在真实成本和样本外为负，则不得通过复杂模型、杠杆或风险参数掩盖。
```

---

## 7. Phase F：第二独立收益源——资金费/基差中性套利

只有 Phase B 的多腿执行、保证金和成本恒等式全部通过后才开发。

新增：

```text
src/aegisquant/research/strategies/funding_basis_carry.py
src/aegisquant/research/models/funding_forecast.py
src/aegisquant/portfolio/multileg_allocator.py
```

正资金费场景的候选结构：

```text
LONG spot
SHORT perpetual
目标净 delta ≈ 0
```

候选价值：

```text
expected_net_carry =
    expected_funding_received
    + expected_basis_convergence
    - spot_entry_exit_cost
    - perp_entry_exit_cost
    - borrow_or_financing_cost
    - expected_legging_cost
    - capital_charge
    - tail_risk_buffer
```

只有：

```text
expected_net_carry
> 2 * all_in_round_trip_cost + uncertainty_buffer
```

才允许进场。

必须具备：

- 两腿预交易容量检查；
- 腿间成交超时；
- 失败腿自动对冲/撤销；
- 实时净 delta 上限；
- 资金费日历和合约规则版本；
- 强平距离和保证金缓冲；
- 交易所/稳定币集中度限制；
- 基差快速扩张压力测试；
- 资金费反转退出规则。

该 sleeve 必须独立样本外通过，不能用趋势 sleeve 的盈利掩盖其亏损。

---

## 8. Phase G：新闻、推文和多模态 AI 的正确接入方式

第一阶段，事件智能只能输出：

```text
risk_veto
position_scale
entry_hurdle_multiplier
expected_slippage_multiplier
data_confidence
```

示例：

```text
交易所宕机/提现暂停/合约异常 -> 禁止新开仓
重大监管或安全事件且来源可信 -> 提高成本门槛、降低仓位
来源冲突或推文真实性不足 -> 不改变方向，只降低置信度
高事件冲击 + 流动性恶化 -> 仅允许减仓
```

不得让 LLM 直接输出 `BUY/SELL` 并下单。

只有完成独立事件研究后，事件特征才可进入预测模型。必须比较：

```text
Market-only
Event-only
Market + Event fused
```

并要求 fused 在冻结样本外、成本后对 Market-only 产生显著增量；否则事件模块保持风险覆盖层身份。

---

## 9. 成本与压力测试矩阵

每个正式策略必须运行：

```text
0x 成本：只用于测量毛信号
0.5x 成本
1.0x 基准成本
1.5x 成本
2.0x 成本
```

并单独消融：

```text
手续费
点差
滑点
市场冲击
资金费
借币
结算费
强平罚金
延迟不利选择
```

压力情景：

```text
延迟：基准、2x、5x
点差：基准、2x、4x
滑点：基准、2x、4x
成交量容量：100%、50%、20%
价格跳空
数据缺口
重复事件
乱序事件
部分成交
取消与成交竞争
资金费尖峰
交易所规则切换
```

成本恒等式必须逐运行成立：

```text
gross_pnl
- fees
- spread
- slippage
- impact
- funding
- borrow
- settlement
- liquidation_penalty
= net_pnl
```

误差只能来自明确的 Decimal 量化规则，并且必须低于预设最小货币单位。

---

## 10. 晋级门槛

以下门槛必须在读取最终 holdout 前写入配置。不得为通过测试而事后放宽。

### 10.1 工程门槛

```text
全部单元/集成/性质测试通过
无同 K 线前视成交
Vector/Event 在支持场景经济结果一致
每根市场事件有 MTM 权益
reduce_only、OCO、强平、借币均有回归测试
同输入、同 seed、同 commit 结果可复现
```

### 10.2 经济门槛

研究候选至少满足：

```text
1.0x 成本下聚合样本外复合净收益 > 0
1.5x 成本下聚合样本外复合净收益 > 0
2.0x 成本下不得出现毁灭性亏损
样本外折净收益中位数 > 0
正收益测试折比例 >= 60%
成本后 Sharpe >= 0.8
Calmar >= 0.5
最大回撤 <= 25%，或显著低于同期 Buy & Hold
成本 / 毛利润 <= 40%
单一折或单一年贡献不得超过总利润的 40%
```

低交易次数时，不得依靠年化夸大结果；必须同时报告非年化折收益和 block-bootstrap 区间。

### 10.3 统计与稳定性门槛

```text
Deflated Sharpe Ratio >= 0.95
PBO <= 0.20
策略收益对小幅参数变化保持同方向
匹配换手随机基线中位数显著低于模型策略
最终结论不能依赖单一牛市折
```

若数据量不足以可靠计算某门槛，返回 `INSUFFICIENT_EVIDENCE`，不得自动通过。

### 10.4 ML 增量门槛

XGBoost/LightGBM 只有在以下条件满足时才可进入最终策略：

```text
B5 在大多数测试折优于 B4
B5 的样本外净 Sharpe 和 Calmar 均不低于 B4
B5 的增量收益 bootstrap 区间不是明显负值
B5 不通过增加长期市场 beta 伪装成预测改进
```

若 ML 未通过，最终策略应退化为：

```text
低频 LONG/FLAT 趋势 + 动态全成本门槛 + 波动率目标
```

这不是失败，而是删除无效复杂度。

---

## 11. 必须新增的测试

```text
tests/unit/labels/test_action_value_symmetry.py
tests/unit/labels/test_executable_entry_time.py
tests/unit/labels/test_funding_sign.py

tests/unit/backtest/test_vector_replays_all_bars.py
tests/unit/backtest/test_final_bar_valuation.py
tests/unit/backtest/test_intraholding_drawdown.py
tests/unit/backtest/test_fill_fragmentation_metric_invariance.py
tests/unit/backtest/test_forced_close_costs.py
tests/unit/backtest/test_automatic_liquidation.py
tests/unit/backtest/test_insufficient_collateral_rejection.py
tests/unit/backtest/test_reduce_only_clipping.py
tests/unit/backtest/test_oco_double_touch.py
tests/unit/backtest/test_cost_attribution_identity.py

tests/unit/research/test_no_zero_threshold_default.py
tests/unit/research/test_three_class_metrics.py
tests/unit/research/test_compounded_equity.py
tests/unit/research/test_purged_walkforward.py
tests/unit/research/test_calibration_train_validation_only.py
tests/unit/research/test_council_can_return_no_alpha.py

tests/unit/portfolio/test_dynamic_economic_gate.py
tests/unit/portfolio/test_hold_current_inside_no_trade_region.py
tests/unit/portfolio/test_target_position_idempotency.py
tests/unit/portfolio/test_pending_order_adjustment.py
tests/unit/portfolio/test_long_flat_only.py

tests/integration/test_cost_aware_trend_end_to_end.py
tests/integration/test_same_signal_before_after_backtest_fix.py
tests/integration/test_walkforward_holdout_firewall.py
tests/integration/test_cost_stress_matrix.py
```

性质测试至少覆盖：

```text
提高全部成本不能机械提高净收益
增加滑点不能改善同一成交路径净 PnL
拆分 fill 数量不应改变固定频率 Sharpe
重复相同 target position 不应重复开仓
reduce_only 永远不能扩大绝对仓位
未来数据 available_time 不得早于决策时间
```

---

## 12. 文件修改映射

| 文件/目录 | 操作 |
|---|---|
| `src/aegisquant/labels/models.py` | 新增动作价值标签与方向成本字段 |
| `src/aegisquant/labels/generators.py` | 删除不对称标签，使用可执行价格和动作净价值 |
| `src/aegisquant/backtest/vector.py` | 向事件引擎传入全部行情事件 |
| `src/aegisquant/backtest/engine.py` | 每事件 MTM、保证金、强平、借币、最终平仓 |
| `src/aegisquant/backtest/fills.py` | OCO、同 K 线双触发、容量与保守成交 |
| `src/aegisquant/backtest/margin.py` | 接入主回测循环 |
| `src/aegisquant/backtest/metrics.py` | 固定频率净值、闭合交易指标、成本瀑布 |
| `src/aegisquant/research/models/baselines.py` | 删除零门槛满仓，改复合收益 |
| `src/aegisquant/research/models/tree.py` | XGBoost/LightGBM 回归与 meta-label |
| `src/aegisquant/research/models/probabilistic.py` | 分位数/概率输出与校准 |
| `src/aegisquant/research/models/uncertainty.py` | conformal/预测区间和失效判定 |
| `src/aegisquant/research/models/economic_gate.py` | 新增模型输出到动作价值转换 |
| `src/aegisquant/research/council.py` | 支持 `NO_PROVEN_ALPHA` |
| `src/aegisquant/research/strategies/cost_aware_trend.py` | 新增低频趋势候选策略 |
| `src/aegisquant/features/market.py` | 新增受控趋势、波动、流动性、funding/basis 特征 |
| `src/aegisquant/portfolio/models.py` | 增加收益分布、成本、动作价值字段 |
| `src/aegisquant/portfolio/optimizer.py` | 固定 no-trade zone 改为动态经济门槛 |
| `src/aegisquant/portfolio/economic_gate.py` | 新增动作比较和滞回 |
| `src/aegisquant/portfolio/transition_costs.py` | 新增完整转仓成本估计 |
| `src/aegisquant/research/validation/*` | 增加经济门槛、随机基线、DSR/PBO、压力测试 |
| `scripts/audit_current_failure.py` | 冻结并归因当前失败运行 |
| `scripts/run_alpha_v4_walkforward.py` | 统一运行所有折和消融 |
| `scripts/run_alpha_v4_final_holdout.py` | 有访问日志的单次最终封存运行 |
| `configs/research/aegis_alpha_v4.yaml` | 冻结全部研究参数和晋级门槛 |

如果仓库现有抽象已覆盖某个新文件职责，应复用现有模块，不要平行复制同类逻辑；但必须保持职责边界和测试要求。

---

## 13. 建议配置骨架

```yaml
strategy:
  id: aegis-alpha-cat-v4
  mode: LONG_FLAT
  decision_timeframe: 4h
  regime_timeframe: 1d
  execution: NEXT_EXECUTABLE_EVENT
  fixed_take_profit: false
  maximum_leverage: 1.0
  maximum_gross_weight: 1.0

trend:
  fast_days_candidates: [7, 10, 14]
  slow_days_candidates: [30, 40, 60]
  center_fast_days: 10
  center_slow_days: 40
  require_parameter_neighborhood_stability: true
  use_hysteresis: true

forecast:
  horizons_bars: [6, 12]
  primary_model: xgboost
  challengers: [lightgbm, elastic_net]
  deep_models_enabled: false
  outputs:
    - expected_gross_return
    - q10_return
    - q50_return
    - q90_return
    - p_net_positive

execution_gate:
  lambda_cost_candidates: [1.5, 2.0, 2.5]
  center_lambda_cost: 2.0
  require_round_trip_cost_on_entry: true
  include_uncertainty_buffer: true
  include_latency_adverse_selection: true
  direct_reversal_allowed: false

positioning:
  target_volatility_candidates: [0.15, 0.20, 0.25]
  maximum_weight: 1.0
  minimum_economic_rebalance: true
  account_for_pending_orders: true

validation:
  train_months: 12
  validation_months: 3
  test_months: 3
  step_months: 3
  final_holdout_months: 12
  purge_by_max_horizon: true
  embargo_bars: 1
  optuna_trial_budget_per_model_per_fold: 30
  random_matched_strategies: 1000
  block_bootstrap_replications: 10000

cost_stress:
  multipliers: [0.0, 0.5, 1.0, 1.5, 2.0]

promotion:
  minimum_oos_net_return: 0.0
  minimum_positive_fold_ratio: 0.60
  minimum_net_sharpe: 0.80
  minimum_calmar: 0.50
  maximum_drawdown: 0.25
  maximum_cost_to_gross_profit: 0.40
  minimum_deflated_sharpe_probability: 0.95
  maximum_pbo: 0.20

safety:
  live_trading: false
  order_submission_enabled: false
```

配置中的候选集合不是要求全部搜索；应优先中心参数，并只做有限邻域稳定性检查。

---

## 14. Codex 执行顺序和提交边界

### Commit 1：固定失败证据

```text
chore(audit): freeze current failed simulation and metric lineage
```

### Commit 2：修复标签和时间语义

```text
fix(labels): replace asymmetric direction labels with executable action values
```

### Commit 3：修复完整行情回放和 MTM

```text
fix(backtest): replay all market events and mark equity on every event
```

### Commit 4：接入经济约束

```text
fix(backtest): enforce margin liquidation borrow reduce-only and OCO semantics
```

### Commit 5：修复指标和委员会

```text
fix(research): compound equity and allow NO_PROVEN_ALPHA
```

### Commit 6：加入透明趋势基线

```text
feat(strategy): add low-frequency long-flat trend baseline
```

### Commit 7：加入动态成本门槛

```text
feat(portfolio): add stateful all-in economic transition gate
```

### Commit 8：加入树模型过滤与概率校准

```text
feat(research): add calibrated tree-based economic meta-filter
```

### Commit 9：完成 walk-forward、消融和压力测试

```text
feat(validation): add frozen walk-forward and economic promotion suite
```

### Commit 10：生成最终报告，但不得启用实盘

```text
docs(results): publish alpha-v4 go-no-go evidence
```

每个提交都必须运行相关测试；禁止最后一次大提交同时改回测器、模型和报告。

---

## 15. 最终产物

```text
artifacts/alpha_v4/before/run_manifest.json
artifacts/alpha_v4/before/metric_lineage.json
artifacts/alpha_v4/before/frozen_predictions.parquet
artifacts/alpha_v4/before/current_failure_report.md

artifacts/alpha_v4/correctness/before_after_same_signal.parquet
artifacts/alpha_v4/correctness/backtest_invariants.json
artifacts/alpha_v4/correctness/cost_identity.json

artifacts/alpha_v4/walkforward/fold_manifest.parquet
artifacts/alpha_v4/walkforward/all_trials.parquet
artifacts/alpha_v4/walkforward/predictions.parquet
artifacts/alpha_v4/walkforward/positions.parquet
artifacts/alpha_v4/walkforward/orders.parquet
artifacts/alpha_v4/walkforward/fills.parquet
artifacts/alpha_v4/walkforward/mtm_equity.parquet
artifacts/alpha_v4/walkforward/trades.parquet
artifacts/alpha_v4/walkforward/cost_waterfall.parquet
artifacts/alpha_v4/walkforward/ablation_results.parquet
artifacts/alpha_v4/walkforward/fold_stability.parquet
artifacts/alpha_v4/walkforward/bootstrap_results.json
artifacts/alpha_v4/walkforward/dsr_pbo.json

artifacts/alpha_v4/holdout/frozen_holdout_manifest.json
artifacts/alpha_v4/holdout/holdout_access_log.jsonl
artifacts/alpha_v4/holdout/final_results.json

artifacts/alpha_v4/reports/strategy_card.md
artifacts/alpha_v4/reports/model_card.md
artifacts/alpha_v4/reports/backtest_correctness_report.md
artifacts/alpha_v4/reports/economic_attribution_report.md
artifacts/alpha_v4/reports/final_go_no_go.md
```

`final_go_no_go.md` 结论只能是：

```text
GO_TO_PAPER_TRADING
NO_PROVEN_ALPHA
INSUFFICIENT_EVIDENCE
REJECTED_FOR_COST
REJECTED_FOR_INSTABILITY
REJECTED_FOR_BACKTEST_RISK
```

即使得到 `GO_TO_PAPER_TRADING`，也只能进入无真实资金的前向模拟，不能启用实盘。

---

## 16. 停止条件

出现以下任一情况，立即停止盈利参数优化并输出失败报告：

1. 修复后的旧信号在零成本下仍稳定亏损；
2. 透明趋势基线在多个滚动测试折和 1.5x 成本下均为负；
3. 盈利只来自一个折、一个牛市或一个孤立参数；
4. ML 不能增量优于简单趋势 + 成本门槛；
5. 结果不能优于匹配换手随机策略；
6. 盈利依赖未实现的借币、免费负现金、未触发强平或遗漏中间 K 线；
7. 只有提高杠杆才转正；
8. 最终 holdout 被重复读取后调参；
9. 成本恒等式无法闭合；
10. 交易次数过少且统计区间覆盖严重亏损。

此时正确结果是：

```text
NO_PROVEN_ALPHA
```

而不是继续扩大模型、指标和参数搜索空间。

---

## 17. Codex 最终报告必须回答的问题

1. 原始约 50% 指标究竟计算了什么？
2. 原始不到 40% 的亏损中，毛信号、手续费、点差、滑点、冲击、资金费、借币和仓位管理各占多少？
3. 修复回测器但保持相同预测后，结果发生了什么变化？
4. 零成本下旧预测是否存在毛优势？
5. LONG/FLAT 是否显著优于 LONG/SHORT？
6. 低频透明趋势是否优于旧曲线预测？
7. 动态经济门槛减少了多少换手和成本？
8. XGBoost/LightGBM 相对简单趋势是否提供真实增量？
9. 利润是否分散在不同折和市场状态，而非集中于单一牛市？
10. 1.5x 和 2x 成本下是否仍可生存？
11. 最终 holdout 是否一次性通过预先冻结门槛？
12. 最终决定是纸面前向模拟还是 `NO_PROVEN_ALPHA`？

---

## 18. 参考案例与采用范围

### 18.1 采用：Globe-Research/bittrends

- GitHub：`https://github.com/Globe-Research/bittrends`
- 可借鉴：多日趋势、移动平均参数稳定区域、walk-forward 思路。
- 不可照搬：论文中的高收益数字、忽略交易成本的假设、逐年选择最优窗口的做法。

### 18.2 采用：2026 成本感知 BTC 机器学习研究

- 论文：`https://arxiv.org/abs/2606.00060`
- 可借鉴：12/3/3 滚动测试、LONG/FLAT 优先、XGBoost 作为强基线、预测幅度必须超过成本相关门槛、交易成本压力与 block bootstrap。
- 不可照搬：其 65% 年化结果。论文自身显示折间稳定性较弱、最大回撤较大，且模型间优势没有得到强统计证明；代码也不是公开 GitHub 仓库。

### 18.3 反例基准：ITheClixs/crypto-return-predictability

- GitHub：`https://github.com/ITheClixs/crypto-return-predictability`
- 可借鉴：purge/embargo、随机游走基线、买入持有对照、多重检验、识别长期 beta 伪装成预测能力。
- 结论用途：提醒本项目接受 `NO_PROVEN_ALPHA`，不能把约 50% 的方向猜测强行转成交易。

### 18.4 弱证据：Jazz-coder107/crypto-ml-momentum-strategy

- GitHub：`https://github.com/Jazz-coder107/crypto-ml-momentum-strategy`
- 其 README 报告传统动量在 2021—2025 年回测中明显高于 ML 策略，但 walk-forward、meta-labeling 和 Deflated Sharpe 仍列为计划项。
- 只用作“简单动量可能优于复杂 ML”的提示，不作为盈利证明。

---

## 19. 一句话执行原则

```text
先证明回测可信；再证明低频毛优势；
再用动态全成本门槛减少无意义交易；
最后才允许 ML 作为过滤器提供增量；
任何阶段无优势就空仓，而不是强制选择一个亏损模型。
```
