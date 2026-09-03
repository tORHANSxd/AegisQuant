# V5-P03 后续动作

只有 P03 完整 CI、独立评审、工件清单和状态绑定通过后，才允许进入 `V5-P04`：

1. 从独立证据分量提取可审计 truth features，而不是 article count 或 Agent vote。
2. 建立可复现 baseline truth model 与 boosting/Bayesian candidate。
3. 建立 source/category/time bucket 的 Brier、ECE、calibration curve 与 retraction delay。
4. 对过期、改稿、来源可靠度漂移和 contradictory evidence 建立 append-only 状态更新。
5. 保持 P03 retrieval、rights、PIT 和 dependency 边界，未校准前不得输出可晋级概率。
