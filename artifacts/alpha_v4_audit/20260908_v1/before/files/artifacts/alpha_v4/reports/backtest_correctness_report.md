# 回测正确性报告

工程验证通过；交易与 Alpha 准入未通过。全量 Python 测试 **1,128 passed、0 failed、0 skipped**，
类型检查为 0 errors / 0 warnings。测试中的 11 个警告来自 Starlette/httpx 和 Nautilus/Pandas 的
依赖弃用提示。逐项证据见 [backtest_invariants.json](../correctness/backtest_invariants.json)、
[JUnit](../correctness/final_pytest.xml) 与 [检查输出](../correctness/final_validation_output.txt)。

## 修复与验证范围

| 契约 | 实现与验收 |
|---|---|
| 动作价值标签 | 可执行下一事件入场，明确 t+h 退出；多空方向成本、signed funding 与不确定性缓冲分开，经济价值不足归 FLAT |
| 行情回放 | 向量入口传入全部行情，包含无订单区间和最后事件；事件/向量完整市场时钟一致 |
| MTM | 每个市场事件估值，同时间戳权益合并；固定频率风险指标不随拆分 fill 数量变化 |
| 终值 | 同时报表 MTM 与含完整退出成本的 forced-close 终值；没有退出容量时不能报告可兑现收益 |
| 资金与保证金 | 现货余额不足拒单；衍生品初始保证金、维持保证金、自动强平及罚金进入主循环 |
| 借币 | 借币权限与上限、利息累计及归还；不能免费做空或使用负现金 |
| 委托语义 | reduce_only 只能缩小绝对仓位；OCO 同 K 双触发采用保守结果；深度、合约乘数与容量受约束 |
| 账本 | 高精度 Decimal 分录严格平衡；不是给不平衡分录放宽容差 |
| 研究指标 | 默认无有效校准不交易，收益复合，方向/类别/交易/账户指标分开；完整 flat-to-flat 交易统计扣除费用 |
| 委员会 | 支持 NO_PROVEN_ALPHA、INSUFFICIENT_EVIDENCE 等弃权结果，selected_model_id 可为空 |
| CAT | 动态全成本比较、保留原仓、pending 差额与下一事件执行；不使用未来开盘价生成数量 |
| 时间防火墙 | 自然月切分、最大持有期 purge、embargo；训练变换与验证校准分别隔离 |
| 多腿恢复 | 两个已出资账本模拟单腿部分成交与失败；撤未完成量、reduce-only 收敛真实裸露风险 |

任务书 §11 列出的 **28 个测试模块**均已运行。六项性质要求覆盖成本/滑点单调性、fill 拆分、
target 幂等、reduce_only 和 available_time；其中成本单调性只在相同实际成交路径前提下成立。
最终持有集防火墙通过未冻结拒绝、已用数据拒绝、跨进程第二次访问拒绝与失败消耗一次访问的验证。

## 成本恒等式

`net_pnl = gross_trading_pnl - fee - spread - slippage - impact - signed_funding - borrow - settlement - liquidation`。
140 个基准“折×策略”逐项费用由十进制字符串独立重算，另检查全部 **1,610** 个折/压力场景。
最大已报告残差为 `4.11543E-23 USDT`，小于固定绝对容差 `1E-8 USDT`；容差不按账户规模放大。
全部场景最终状态为 `NO_POSITION`，MTM 与 forced-close 终值一致。

完整金额见 [cost_identity.json](../correctness/cost_identity.json)。金额合计为 14 个独立
10,000 USDT 折账户的费用之和，不应当当成一个复合账户的实际支出。

提高成本时，固定的委托数量可能因现金不足而失去可执行性。实际发现 **16 个折/压力场景**成交路径
改变：B2 在 1.5x 的 5 折；2x 中 B2 5 折、B3 1 折、B5 2 折、LightGBM 2 折、ElasticNet 1 折。
这些结果记录了拒单和实际成交，属于资金约束压力，不能宣称“相同 fill 下只改变成本”。
其余场景的成交时间、方向、数量核对相同。保留完整原始压力结果，没有为了匹配路径给予免费资金。

## 同信号前后与故障记录

原实际亏损路径调用的是归一化收益评估器，并未调用事件/向量引擎。
因此不能把此次发现的所有引擎缺陷都归为原始 -38.82% 的成因。
[before_after_same_signal.parquet](../correctness/before_after_same_signal.parquet) 从冻结诊断派生：
原 BTC/ETH `logistic_core` A0 为 -38.8225%，完整时钟与初始等额资金账户 A1 为 -34.7542%。
该桥接修正跨资产资金分配与成本时点，不改变冻结预测；缺少原账户规模/数量，仍属 NAV 归因。

已保留两次失败尝试：不规范源 K 线导致加载拒绝，以及高精度成本归因残差导致首折压力回放失败。
修复针对完成 K 线选择与精确求和，没有改变趋势、模型或盈利门槛。完成运行的代码快照为 `7ebec24`；
后续 carry、风险覆盖层及拟合计数修正没有触发重新 OOS 评估。

原诊断仍保留 `TARGET_EXECUTION_ALIGNMENT_FAILURE_REQUIRES_INVESTIGATION` 筛查标记；
核验全部 60,480 个 next-open 标签与原行情价格、时间顺序一致，没有确认的执行时序实现错误。
其中 BTC 的 `target_start - decision_time` 均为 1 ms。最佳 shift 为 +1 只触发调查，不构成错位证明。

10 万 K 线完整向量回放阶段基准耗时 5.79 s，10,000 事件耗时 0.55 s，固定输入重复哈希一致；
详见 [经济约束基准](../correctness/economics_benchmark.json)。这是开发机测量，不能代替线上容量 SLA。

历史 P07 标签证据由旧语义生成，其旧生成器 `--check` 会报告内容不再一致；历史文件保留原状，
没有通过批量重生成把旧报告冒充当前验收。当前标签修复由 v4 专项与全量测试验证。
真实历史费率等级、订单簿、保证金档位和 carry 双腿执行证据仍不足；工程通过不消除这些限制。
