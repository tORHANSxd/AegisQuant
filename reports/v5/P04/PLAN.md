# V5-P04 — Truth Council + Calibration

- Evidence Tier: `DEVELOPMENT`
- Alpha Promotion Eligible: `false`
- Live Trading Locked: `true`

## 规格边界

本阶段严格对应 v5 SSOT 第 599–720、1341–1424 行及 V5-P04 第 2105–2121 行，只实现
PIT evidence feature extraction、Truth candidate council、独立概率校准、Truth 状态回放和
source/model reliability decay。P05 event surprise、P06 causal layer、真实准确率和所有交易
Promotion 均不提前声明。

## 实施顺序

1. 从 P03 已选择的 evidence hit/graph 提取十五项可审计模型特征；所有外部标量先绑定 PIT
   input snapshot 的 lineage/hash/availability，并把 LLM confidence 留在审计字段而非模型输入。
2. 建立带 feature/label availability 的 Truth calibration sample，并用 purge/embargo 的时间
   顺序拆分 train、validation、calibration、test。
3. 同一 split 上比较 Logistic baseline、Gradient Boosting 和经验层级 Bayesian candidate；
   复杂候选必须在 validation Brier 上达到最小改善。
4. calibration split 单独拟合 Platt、isotonic、temperature 与 beta calibrator；test 只评估，
   不参与选择。
5. 报告 Brier、LogLoss、ECE、MCE、calibration slope/intercept、reliability diagram、分类
   指标和 high-confidence bucket accuracy。
6. 用 hash-linked revision 重放可逆 Truth state，并实现来源历史恶化与 Truth 模型校准失真
   的自动降级。
7. 生成 schema、确定性开发证据、负向测试、完整 CI 和内容寻址工件清单。

## Acceptance

- train、validation、calibration、test 必须时间有序、互斥，且测试标签不得选择模型/校准器。
- fold 必须由声明的 split policy 重算通过；上游标签必须在下一分区前可用，同一 claim 不得
  通过更换 sample ID 跨分区重复。
- 三个 Truth model family 和四个二元概率 calibrator 均有可审计比较结果。
- 最终 probability 必须来自校准模型，不能等于 LLM confidence 或 Agent vote。
- Brier、LogLoss 与十桶 reliability diagram 必须有独立 test 证据。
- historical replay 必须在相应 decision time 得到 `RUMOR → VERIFIED_PRIMARY → RETRACTED`。
- correction/retraction/false-claim rate 恶化必须降低 source reliability；高置信失准必须推动
  Truth model 进入 `DEGRADED/RESTRICTED/RETIRED`。
- 完整 V5-P04 CI、历史 manifest 的工作树内 SHA/结构自洽检查和最终当前工件清单全部通过；
  没有外部签名锚时不声称历史不可篡改。
