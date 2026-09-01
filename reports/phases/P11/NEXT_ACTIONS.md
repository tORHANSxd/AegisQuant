# P11 后续动作

1. 保持 `LIVE_TRADING=false`、`live_trading_locked=true`；P12 及后续阶段不得获得真实账户或绕过
   `RiskDecision` 的能力。
2. 固化 P11 最终证据提交和工件清单后再启动 P12，并先建立 P12 需求追踪矩阵与实施计划。
3. P12 的执行模拟必须只消费仍在有效期内的 Paper `OrderIntent`，校验 proposal、risk decision、
   账户、策略、资产与幂等键，不允许把 `PortfolioProposal` 直接翻译成真实订单。
4. 未来若接入真实风险数据，只允许通过本地秘密引用和只读账户快照；不得在对话、仓库、日志或报告
   中写入密码、Cookie、验证码或 API Secret。
5. 在统一正式验收前，补充真实数据的容量/冲击校准、极端场景、政策签名生命周期和恢复演练；所有
   负结果和熔断事件必须保留。
6. P11 正式验收仅在项目业主发起统一验收后执行；届时再生成 `ACCEPTANCE.md` 和真实
   `accepted_at_utc`。在此之前保持 `verified_acceptance_deferred`。
