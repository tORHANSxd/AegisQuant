# B4 执行与成本契约

`python -m scripts.run_alpha_v5_execution_diagnostics --config configs/research/alpha_v5_execution_contract.yaml --preflight-dir <真实检查回执目录>` 只生成一次协议报告，不加载市场数据或训练模型。真实数据/分割仍为 null。

- `ImpactModel` 将曲线、反函数、参与率单位、horizon 和已覆盖范围绑定。旧执行 LINEAR_PROXY_V1、旧组合 LEGACY_SQRT_CAPACITY_V0 保留；显式 model 与 signal/schedule/liquidity horizon 不一致即失败。代理身份不能升级为实证。
- `FillSlice.reference` / `CostSchedule.evidence` 是显式 V2 包装。默认不进入旧序列化 payload。MID、BBO、DEPTH_VWAP、BAR_OPEN_PROXY 分离；MAKER_LIMIT 用于已给出队列证据的限价参考，不冒称 BBO。
- `HistoricalCostBook.at` 保留执行有效时点选择；`decision_at` 额外要求历史账户证据及 available_at。实际费率晚知不会反写为决策已知。
- 逐笔 `FeeAccountState` / `settle_execution_fee` 分别处理 standard、special、tax、role/side、标准费用优惠、失效、余额不足和 FX 不可用回退。新费率输入缺账户状态则拒绝，不能由旧 engine 静默按 quote fee 结算。金额使用现有 canonical Decimal 精度。
- `SPOT_NATIVE_FEES_V2` 必须使用以 `:native-fees-v2` 结尾的新 AccountingPolicy 版本。交易+费用余额不足先拒绝；base fee 的 FIFO 消耗、处置损益分录和 rebate lot 随原成交记录一起重建。实物币支付费用的处置损益使用 clearing 对手科目，不产生计价币现金。第三费币若存在其他交易 lots，目前明确失败，避免偷偷留下未处置库存。第三币 MTM 仍需要真实可用 FX。
- `EventLiquidityBudget` 复用既有撮合函数，作用于单 instrument/venue 的一个已知累计成交窗口截止时点。preview 不扣减实际流动性，资金结算后才 commit；同事件深度与窗口双向绝对量共享、fill id 幂等、残余可追溯。当前严格工具输出 SYNTHETIC_ONLY；不是整个历史引擎已接入实证模型。
- 校准残差只接受提供的执行记录并检查原生费用精确到 quantum、200 样本/20 日、1bp 中位偏差、日区块 q95 超越率区间。来源核验是独立必要条件；合成记录通过不证明真实费用或容量。
- 三种 CostMode 继续复用，只有 SAME_FILL_SHADOW 要求更差费用不改善影子净值。funded 路径不作单调断言。

历史策略回放、真实收益模型/校准拟合、最终留出访问、真实订单均为 0；NO_PROVEN_ALPHA、CASH 及四个关闭开关保留。B3/B4 的真实矩阵和校准需数据与相应授权，不能用协议完成替代经济验收。
