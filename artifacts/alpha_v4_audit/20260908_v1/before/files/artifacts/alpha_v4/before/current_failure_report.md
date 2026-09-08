# Alpha v4 当前失败证据冻结

EvidenceTier: `OOS_DEVELOPMENT`。Phase A 状态：`BLOCKED_MISSING_FAILED_PREDICTIONS`。
本次只读原始公开数据并冻结现有输出，没有重新训练、调用网络或修改策略。

## 指标已定位

- `50.0810%` 来自所选元策略的逐样本二分类方向准确率，不是价格曲线成功率或完整交易胜率。
- 同一元策略净复合收益为 `20.637901%`，最大回撤为 `56.889898%`。
- `-38.8225%` 来自 `logistic_core` 候选，其方向准确率为 `53.508598%`。两个用户指标不能拼成同一运行。
- 上述字段均来自 `reports/v5/REAL_DATA_BACKTEST/BACKTEST_REPORT.json`；具体公式及源码位置见 `metric_lineage.json`。
- 使用独立的公开市场研究收益向量评估器，已采用 LONG/FLAT、逐期复合和最终退出成本。任务书对旧 baselines evaluator 的缺陷描述不能直接归因到该运行。

## 已冻结与 A0 复现

保存 60,480 行所选元策略逐样本数据，BTC/ETH 各 30,240 行。
`frozen_predictions.parquet` 的每行标记 `SELECTED_POLICY_ONLY`；它不是亏损候选的完整预测。
使用原始 `return_path` 和 `performance_metrics`，不重新拟合模型，复现每行毛收益、成本、净收益以及报告的准确率和净复合收益（误差阈值 `1e-12`）。
账户初始资金未记录；`initial_equity=1` 仅为复核复合收益的归一化净值单位。
原流程无订单数量，`order_quantity` 保留 null，不用仓位权重伪造订单。

## 尚不能进行的归因

原 OOS CSV 只记录 selected policy；原 RUN_MANIFEST 与 TRIAL_LEDGER 未登记候选的完整逐样本预测或模型文件。
因此无法冻结 `logistic_core` 的完整原始预测，也无法在相同预测条件下完成亏损候选的 A0–A10。
冻结文件中即使包含少量 selected_candidate=logistic_core 的行，也不代表未选中时的完整序列。
原成本是每单位换手 10 bps 手续费和 3 bps 合并执行成本假设。点差、滑点、冲击、资金费和借币的实际分项没有观测证据；不能反推出它们各占原亏损多少。

## 继续条件

优先提供原运行 `logistic_core` 的逐样本预测导出（sample_id、概率或原始预测、仓位及时间）。
如原数据确实未保存，需要用户明确允许按原提交、数据、配置和 seed 重建候选，并标注 `RECONSTRUCTED_BASELINE`；重建结果不能声称是原预测。
依据任务书 §2.2“冻结当前预测，不允许重新训练”和 §14 提交顺序，当前不进入策略修改、参数优化或最终 holdout。
实盘交易及订单提交继续锁定；现有数据已经用于开发 OOS，不能重新命名为未读过的最终 holdout。
