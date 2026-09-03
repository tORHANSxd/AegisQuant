# V5-P06 负结果与禁止外推

- `EventResponseDataset`、历史状态、市场路径、propensity 与 outcome 均为确定性 `DEVELOPMENT`
  fixture；没有使用真实公开事件或交易行情。
- matched DID 的 `1.5`、synthetic control 约 `1.0`、AIPW 的 `1.0` 是预设可恢复效果，不是发现的
  市场异常收益。
- timestamp/asset placebo 使用人为零分布，treatment permutation 使用构造分组；其经验 p-value
  只验证算法和门禁，不能作为真实显著性证据。
- 单 treated event 不提供标准误和置信区间，避免拿 control-only 波动伪装采样不确定性。
- 坏 pre-trend 的 negative control 即使标成 `FINAL_HOLDOUT` 也被 causal gate 阻断；这证明
  fail-closed，不证明主样本已识别。
- 未证明 no-unobserved-confounding、parallel trends、stable treatment、donor exchangeability、
  interference absence 或 event-time exogeneity。
- 未评估事件特征相对纯市场模型的 predictive increment，也未执行成本、滑点、容量或收益回测。
- 未产生真实因果效应、预测准确率、Alpha Promotion 或任何交易授权。
- Live trading、订单提交和真实账户连接保持关闭。

拿预先写好答案的四行样本跑出 `effect=1`，然后宣布掌握市场因果律，这不是研究，是给答案
配演算过程。P06 只交付可被证伪的尺子，真实结论还得等公开 PIT 数据上场挨打。
