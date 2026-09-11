# 已保存模拟记录的只读补充核验

入口 `python -m scripts.audit_alpha_v5_saved_runs --config configs/research/alpha_v5_saved_run_audit.yaml --preflight-dir <检查目录>` 沿用已有 claim、哈希链、零研究预算守卫与封存函数。新增五个文件，不修改旧实现或任何历史结果。

固定读取原 R5 v3 全部 55 个保存 run 和原 F0 的 70 个季度分区。结果/trace bytes 必须先匹配 B0 已封存 catalog 或修改前 baseline 的 SHA256 与长度，然后才解压 JSON 或读取 parquet。解析是只读原模拟结果，不执行 engine、ledger 命令、市场回放、模型拟合或重新定价成交；使用已有纯 `resample_equity` 和 `execution_reason`。

核对 trace→order→fill→ledger 的已保存 ID、数量、时钟与费用资产；每条原账本记录重算哈希链并检查逐资产借贷平衡。复用既有 LotChange 模型校验数量与生命周期，并将 lot 的原始成交 ID、单位、数量、开仓价格及费用连回保存 fill；账本幂等键须匹配冻结模拟器的 `simfill:<fill_id>`。从已有原生 CASH postings 和 lot changes 检查每个已保存 MTM 的现金、净库存及已记录价格。它验证保存记录的内部一致性，不能证明模拟器等价于真实交易所，也不是重跑会计策略。金额算术容差预先固定 1e-18 USDT，数量终态严格为零；报告全部检查次数、失败数和最大算术残差。

共同四小时日历沿用原因果标记前填。原始行情 gap 仍是缺口；每格保留源标记时间，超过四小时的前填计数单列。F0 分区仅合并资金、仓位和净值完全相等的重复边界，不删除付费退出。最差窗口取完整日历中 ceil(5%×N) 的最小净收益并纳入所有临界值并列；全部五币逐窗列示。现金和库存价值变化相加必须等于净值变化，再加总到组合。只能称原模拟账户贡献，不能据此声称因子 alpha 或独立尾部因果解释。

门槛漏斗统计覆盖所有已保存 trace 行的终态理由，未记录的内部每一道 gate、veto 前 target、二次取整前后全状态、外部 ack/cancel/queue 仍 NOT_VERIFIED。复核到期状态由前行保存状态与提交事件核对；没有订单也可能更新到期复核，不将最后成交时间替换复核时钟。

所有失败均保留且不修改原结果。此前 B0/B7 缺口报告保持冻结，本补充只提升已经核对的记录范围。真实 PIT、费用/规则/盘口/延迟、完整试验史、真实 ML/组合验证和未使用留出仍依赖外部证据及独立授权。`NO_PROVEN_ALPHA / CASH` 和四项关闭状态继续有效。
