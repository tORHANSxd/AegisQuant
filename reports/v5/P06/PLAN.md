# V5-P06 — Event Response Dataset + Causal Layer

- Evidence Tier: `DEVELOPMENT`
- Alpha Promotion Eligible: `false`
- Live Trading Locked: `true`

## 规格边界

本阶段严格覆盖 v5 SSOT 的 `EventResponseDataset`、matched historical states、matched event
study、synthetic control、doubly robust AIPW、placebo 与 causal diagnostics。真实公开数据回放、
OOS 预测增量、成本后收益、P07 Forecast Council 2.0 和任何交易 Promotion 均不提前声明。

## 实施顺序

1. 建立 revision-aware、PIT、内容寻址的事件响应行与数据集，覆盖 5m/30m/4h/1d/7d、
   vol/liquidity/tail/MFE/MAE，并绑定 feature/label/universe/source lineage。
2. 从同一个 `CanonicalEvent` 受约束注入事件身份、revision、可用时间、Truth、source quality、
   novelty、reflection 与 Surprise，拒绝合法哈希之间的拼接伪造。
3. 只从处理时点之前、outcome 已知的历史状态中确定性匹配；实现 matched DID 点估计。
4. 为长 horizon 提供 simplex 约束 synthetic control，为群体处理提供 PIT nuisance-bound AIPW。
5. 生成可复算的 pre-fit、pre-trend、balance、overlap、timestamp/asset/treatment-permutation
   placebo，并用固定 policy fail closed。
6. 生成 Schema、确定性开发证据、负向/攻击测试、完整 CI、独立只读评审和内容寻址 Manifest。

## Acceptance

- 必须产生 pre-treatment fit report。
- 必须执行 event timestamp placebo、asset placebo 与 treatment permutation。
- pre-trend、overlap、balance、placebo、control count 或识别假设不合格时不得宣称 causal effect。
- `DEVELOPMENT` 证据即使诊断通过也不得升级为真实因果、Alpha 或预测准确率声明。
- 任何 future event/feature/label/donor/nuisance training 输入都必须 fail closed。
- 所有输出保持 `NO_PROMOTION`、订单关闭与 Live 锁。
