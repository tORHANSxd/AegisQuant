# B5 组合与资金桥接

`python -m scripts.run_alpha_v5_portfolio_diagnostics --config configs/research/alpha_v5_portfolio_contract.yaml --preflight-dir <真实检查回执目录>` 仅输出一次协议报告。实际联合路径未输入，九个历史场景预算为 0。

- `estimate_covariance(..., contract=...)` 显式区分 TOTAL 和 RESIDUAL；TOTAL 不能另加市场因子，RESIDUAL 只接受已定义且正交的 FactorRisk。原数值接口和结果序列化保留，明显非 PSD 矩阵在任何接口都拒绝。
- 特征值先按资产 ID 排序计算，容差固定为矩阵最大绝对元素的 `1e-12`。负特征值越界失败；容差内按固定对角 jitter 修复，记录输入最小特征值和修正 Frobenius 范数。不能为追求收益调 shrinkage。
- `daily_covariance_from_rows` 只处理提供的 90 个完整 UTC 日，半衰期 30 日、diagonal shrinkage 0.20、年化 365.25。收益使用小数单位；future rows 不进入过去估计，缺失币种或日期拒绝。
- `build_portfolio_proposal` 新增显式 `raw_target_weights` 与 `hard_risk_reduction`。新路径不调用均值优化、不将二元信号假装期望收益；继续复用原约束、容量与 risk engine。硬降风险产生的未解决约束保留在 proposal，不表示已经修复实际持仓。
- `account_from_ledger` 从原 ledger 对账，限定同账户/场所、同 quote、单位现货、long/flat。交易资产的现金余额必须与净 FIFO 库存一致；可用现金为场所 available 和 ledger 扣除未结算及 pending BUY 预留后余额的较小值。输入余额/FX可知时间必须不晚于决策。
- `plan_shared_capital` 仅生成研究数量建议；资金竞争按比例分配再向下取整，输入币种顺序不改变结果。未成交 SELL 不释放现金或抵消 BUY 风险，pending 反向冲突先请求撤单，未确认前不释放预留。partial fill 后必须以新 ledger 和独立 risk snapshot 重算。调用者必须提供持久化的上次风险状态及下一条 transition 序号；本函数复用既有状态机，只返回更保守的自动 transition，由调用者写入既有控制日志。新快照恢复正常不会自动清除原风险状态。
- `SPOT_NATIVE_MTM_V2` 是显式估值参数，现货余额已包含市价变化，因此只追加衍生品浮盈；旧 `LEGACY` 估值默认保留。现货总浮盈可在原 valuation lots 查看，不能再次加到 NAV。
- `cvar_evidence` 的点估计不能声明安全，独立尾部区块不确定性未识别时返回 UNKNOWN。`drawdown_history` 分开记录全期与 30 日窗口。恢复仍需已有状态机的明确研究复核，不自动开启风险或生产。

任务书风险数值仅冻结为待采用的研究起点。合成测试通过不等于真实 PIT、费用、资金历史或尾部证据通过，仍为 NO_PROVEN_ALPHA / CASH。
