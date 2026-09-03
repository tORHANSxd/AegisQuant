# V5-P10 验收记录

- Evidence Tier: `DEVELOPMENT`
- Alpha Promotion Eligible: `false`
- Decision: `PASS_WITH_RECORDED_NEGATIVE_RESULTS`
- Real-world Forecast Accuracy Claimed: `false`
- Real-world TCA Claimed: `false`
- Forward Evidence Present: `false`
- Final Holdout Opened: `false`
- Order Submission Enabled: `false`
- Live Trading Locked: `true`

P10 已完成 Forecast → Truth Gate → Price-In Gate → Cost → Net Edge → Portfolio → Independent
Risk 的无旁路、非执行决策边界。最终结果只能互斥地落入研究型 `DIRECTIONAL_ALPHA`、保护型
`RISK_OVERLAY` 或第一类 `NO_TRADE`；新闻、事件或模型建议均不能绕过成本、组合与风险门禁。

`ExecutionCostModelV2` 覆盖手续费、点差、冲击、滑点、资金费、借贷费、延迟、撤单、拒单、
排队和清算尾部共 11 项成本，并区分 BACKTEST/PAPER/LIVE。Maker 队列支持保守模式和绑定六项
输入的 replay 模式；排队概率进入成交机会调整后的 gross edge。TCA 失准会降低置信度，不能靠
乐观成本估计放行交易。

Net Edge 从同一组 Forecast 与 Cost 概率场景重算，并依次执行 expected net edge、正收益概率、
LCB、edge/cost ratio、Truth、Price-In、不确定性、OOD、数据质量、事件增量、Portfolio 与 Risk
门禁。阈值按 asset×horizon×sleeve 显式版本化，`0.60` 只允许作为 DEVELOPMENT bootstrap，
OOS 阈值必须绑定证据工件。

独立复核发现的风险目标拼接、队列概率未入经济性、场景数量无上界和风险对象构造绕过均已修复：
Risk 必须逐项匹配 asset、instrument、strategy、account、当前权重与建议目标权重；边界重新验证
Portfolio/Risk 载荷；场景数量上限为 4096。剩余负结果是结构和内容哈希不能证明风险服务真实签发，
已记录为 `V5-RISK-020`，要求 P12 绑定签名策略、风险快照、告警与不可变授权收据。

最终完整 CI `69/69` 通过：主环境 `969 passed / 11 warnings`，候选 Python 3.14 环境
`653 passed / 11 warnings`，188 份 Schema 工件无漂移；Ruff format/lint、Pyright strict、Bandit、
安全、Web lint/typecheck/unit/Storybook/build/E2E 与 P00-P09 冻结 Manifest 自洽检查全部通过。
安全扫描四项通过，`secret_finding_count=0`；未访问真实账户或 secret store。P10 架构边界加定向
测试 `40 passed`。

阶段按记录负结果通过并授权开始 `V5-P11`。本阶段没有真实公网 PIT OOS、Forward、真实 TCA、
Paper、Shadow、Testnet 或 Live 证据，不声明真实准确率、成本后收益或可交易 Alpha；Final Holdout、
订单提交与 Live trading 继续锁定。
