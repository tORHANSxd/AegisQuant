# V5-P05 后续动作

P05 已按 `PASS_WITH_RECORDED_NEGATIVE_RESULTS` 验收，`V5-P06` 获准开始，但尚未实施。
P06 必须：

1. 构建 revision-aware 的 PIT event response dataset，明确事件时点、首次可知时间和市场窗口。
2. 实现 event study、matched control、double/debiased ML、synthetic control、placebo 和 pre-trend。
3. 区分事件相关性、预测增量与可识别因果效应，禁止把事后价格波动自动归因于事件。
4. 对真实公开事件与市场数据执行无泄漏 replay，并保留 failed/insufficient-identification 结果。
5. 继续保持 rumor directional alpha 禁用、研究候选不等于订单、Live trading 锁定。
