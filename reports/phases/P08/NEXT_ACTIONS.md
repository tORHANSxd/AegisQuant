# P08 后续动作

1. 保持 `LIVE_TRADING=false`、`live_trading_locked=true`，不连接真实账户，不打开最终 holdout。
2. 等项目业主显式发起统一正式验收后，在目标 4070 Ti 上重跑显存、训练时间、推断延迟和
   OOM 恢复；通过后才能处理 `P08-A07`，并重新运行当时仍适用的完整门禁。
3. 统一验收时再生成 `ACCEPTANCE.md`、写入真实 `accepted_at_utc`；在此之前不得把
   `verified_acceptance_deferred` 解释成正式接受。
4. 只有收到项目业主明确的 P09 启动指令后，才允许开展外部知识/源码静态分析；届时先静态
   审查 Kronos 等外部代码，不能借 P08 插件清单提前执行。
5. 若后续接入真实数据或云 LLM，必须先固化 Source Policy、数据权利、first-seen、调用预算、
   供应商保留策略和秘密注入方式；禁止把凭据写进仓库、日志或 Proposal。
6. 真实研究评估必须复用 P07 point-in-time 数据集、P06 成本/回测口径和 P05 权威账本，并继续
   报告失败模型、负收益、abstain 与不适用项，不得只展示最佳结果。

本报告只列后续动作，不表示已启动 P09。
