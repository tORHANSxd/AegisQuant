# V5-P08 负结果与禁止外推

- 尚未运行真实公网 PIT 数据、外部模型训练、真实 OOS 或 Forward；事件预测准确率仍未知。
- 当前阶段允许且必须保存“Market+Event 不优于 Market-only”或置换不退化的结果。
- 确定性消融中 Truth permutation 未达到最小退化阈值，因此 P08 明确记录
  `TRUTH_PERMUTATION_NOT_DEGRADED`，事件增量门禁未通过。
- 任何确定性 fixture 中的非零 EventIncrement 都只是差分契约样本，不是事件 Alpha。
- 未打开 Final Holdout，未产生 Promotion、订单、真实账户连接或 Live trading 授权。
