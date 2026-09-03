# V5-P05 — Event Canonicalization + Surprise + Price-In

- Evidence Tier: `DEVELOPMENT`
- Alpha Promotion Eligible: `false`
- Live Trading Locked: `true`

## 规格边界

本阶段严格覆盖 v5 SSOT 的 CanonicalEvent、actual/expected/whisper、Surprise、Narrative
Diffusion、Market Reflection / Price-In 以及 V5-P05 验收项。P06 causal effect、P07 Forecast
Council 2.0、真实准确率、收益回测和任何交易 Promotion 均不提前声明。

## 实施顺序

1. 以 P03 EventCluster 和 P04 TruthAssessment 为输入建立内容寻址、revision-aware、PIT 的
   CanonicalEvent，并阻止状态与时间倒退。
2. 将 actual、consensus 和 whisper 建模为独立带时间与 lineage 的值，再从同一 snapshot 重算
   surprise。
3. 保存首次来源、首次已验证来源、传播速度、跨平台扩散和市场响应延迟。
4. 以十个必需维度生成版本化 MarketReflectionScore；缺失、过期或未来数据全部 fail closed。
5. 在事件影响与 world fusion 两条方向路径前强制统一门禁；旧调用缺少门禁时归零并 abstain。
6. 生成 schema、确定性开发证据、负向测试、完整 CI、独立只读评审和内容寻址工件清单。

## Acceptance

- 高 price-in confirmed event 默认不得产生 directional signal。
- rumor 与 confirmed 必须分离，rumor 只能进入风险覆盖语义。
- actual/expected/whisper、diffusion、reflection、event revision 和 gate 必须符合 PIT。
- 缺失或过期 reflection 输入不得退化成“按零分处理”，必须显式质量降级并阻断方向候选。
- 任何兼容入口都不得绕过 canonical event revision 和 directional gate。
- 所有输出保持 `DEVELOPMENT`、`NO_PROMOTION` 与 Live 锁。
