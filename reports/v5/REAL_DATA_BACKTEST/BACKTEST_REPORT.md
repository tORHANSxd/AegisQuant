# AegisQuant 真实公开市场样本外回测

- 模式：`OOS_DEVELOPMENT_WALK_FORWARD`（不是最终盲测）
- 方向准确率：`50.0810%`
- 方向准确率 95% 块自助区间：`[49.7039%, 50.4845%]`
- Brier：`0.389959`
- ECE（10 桶）：`0.285908`
- 扣费后复合收益：`20.6379%`
- 年化 Sharpe：`0.3383`
- 最大回撤：`56.8899%`
- PBO：`0.0714`
- DSR 概率：`0.0130`
- White Reality Check p 值：`0.1239`
- 全局结论：`NO_PROMOTION` / `KEEP_LIVE_LOCKED`

## 候选对照

| 候选 | 方向准确率 | 95% 块自助区间 | 扣成本复合收益 | 年化 Sharpe |
|---|---:|---:|---:|---:|
| `always_flat` | 49.4874% | [49.0491%, 49.8926%] | 0.0000% | 0.0000 |
| `always_long` | 50.5126% | [50.1041%, 50.9244%] | 113.3046% | 0.6711 |
| `logistic_core` | 53.5086% | [53.0572%, 53.9253%] | -38.8225% | -2.1760 |
| `logistic_slow` | 51.7526% | [51.3640%, 52.1429%] | -40.2114% | -0.6777 |
| `logistic_full` | 53.3284% | [52.9629%, 53.7368%] | -45.8830% | -1.8837 |

所选元策略方向优势：`NOT_DEMONSTRATED_CONFIDENCE_INTERVAL_INCLUDES_50PCT`；最佳方向候选：`logistic_core` / `SURVIVES_DIRECTION_ACCURACY_FDR`；稳健净 Alpha：`NOT_DEMONSTRATED`。即使部分分类器方向命中率显著高于 50%，其幅度仍不足以覆盖预设交易成本；当前正收益主要来自滚动验证选择出的 long/flat 市场 Beta 暴露，并不构成预测 Alpha 证明。

## 结论边界

该结果只衡量 Binance Spot 的 BTCUSDT/ETHUSDT 一小时市场方向预测。成本为预先声明的保守假设，不是账户真实 TCA；事件真值、因果链、新闻时延、Forward/Shadow 和最终盲测均未被验证，因此无论历史指标好坏都不得晋级实盘。
