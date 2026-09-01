# P07 Baseline Scoreboard

开发期 OOS 结果；最终 holdout 未开启。本表按状态、净收益、DSR 和回撤综合排序，不以单一 Sharpe 排名。所有金额均为归一化收益率。

| Candidate | Modality | Gross | Fee | Spread | Slippage | Impact | Funding | Borrow | Net | Sharpe | PSR | DSR | PBO | Max DD | Positive folds | Event increment | Trials | Status |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Linear Fused | FUSED | 0.026 | 0.001 | 0.001 | 0.001 | 0.001 | 0.001 | 0.001 | 0.02 | 1 | 0.8 | 0.7 | 0.2 | 0.1 | 4/5 | 0.001 | 10 | PASSED_DEVELOPMENT |
| Elastic Net Rejected | FUSED | -0.004 | 0.001 | 0.001 | 0.001 | 0.001 | 0.001 | 0.001 | -0.01 | 3 | 0.8 | 0.7 | 0.2 | 0.1 | 4/5 | 0.001 | 10 | REJECTED |

## Negative results

- `elastic-rejected`: 高 Sharpe 未通过成本压力与跨折一致性，保留为负结果。

## Holdout

所有条目的 `final_holdout_opened=false`。冻结前不可读取最终 holdout；本表不能作为实盘晋升证据。
