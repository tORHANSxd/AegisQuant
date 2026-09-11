# B3：共同风险基准的契约与合成验证

本批延续零历史回放、零真实模型/校准拟合、零最终留出访问和零订单约束，完成 B3 的工程契约。
新增入口 `scripts/run_alpha_v5_benchmark_diagnostics.py` 只有只读契约报告功能；没有历史运行命令、
行情参数或收益搜索。独占 generation 为 `alpha-r5-benchmark-contract-20260910-v1`，只消费一次报告作业。
旧 R5、R4、B0/B1、B2 产物及全部失败记录保留，不自动提交、推送或归档。后续工程使用各自独立 generation。

## 六臂及账户身份

| 新矩阵臂 | 信号 | 普通仓位控制 |
|---|---|---|
| F5_MATCHED | 始终持有 | G0/F3 缓冲 |
| SIMPLE_TREND | 现有 10/40 趋势 | G0/F3 缓冲 |
| G1_PASSIVE | 始终持有 | 冻结 G1 |
| G1 | 现有 10/40 趋势 | 冻结 G1 |
| PASSIVE_FIXED_QTY | 始终持有 | 入场后实际数量固定 |
| TREND_FIXED_QTY | 现有 10/40 趋势 | 入场后实际数量固定 |

另列 CASH。六个风险臂共用当时可知输入、原 A1 gate、执行及终止约定；G0/G1 的参数直接使用
现有 `controls()` 构造器。报告中的 Decimal 为字符串、timedelta 为整数秒。
数量固定臂仅定义保持实际已成交数量的普通控制，硬退出/硬上限、pending、部分成交和资金限制仍须走
已有路径；本批未实现它的执行适配，也未取得引擎等价证据。

相同事前风险限制不意味着实现波动完全相同。不得用全样本实现波动缩放交易权重。
资金模式固定为五个各 10,000 USDT、无转移的独立 sleeve，不能混入共享资金组合或 shadow 排名。
`F5_MATCHED` 不等于把旧 F5 改名；旧 F0/F3/F5/99%buyhold 仅作为历史参考。

`validate_benchmark_paths()` 接收已提供的经济路径，检查配置、输入/risk/execution hash、日历、
资金模式、现金流、首尾资金边界和 readiness；缺失行、未知 ready、影子账户和未平终值均拒绝。
CASH 不产生订单、成交、成本或收益，四小时零风险期完整保留。共同 ready 子集只作诊断，不能删日期。
相同配置的经济 payload 比较器不负责生成订单；合成记录相同不等于实际策略执行已经复现。

## 统计及归因

新增 `PairedLogGrowth` 使用 `mean(log(1+r_candidate)-log(1+r_benchmark))`，CI 与单侧居中检验
都对应同一统计量。统计核心的单位是每个登记观测点；本批契约固定为 UTC 日，不能把四小时输出冒充日值。
同一 circular block 行索引同时作用于全部列；观测收益必须有限且大于 -100%。对数空间直接累计，
不从已下溢到 -100% 的复合结果反推 log growth。CASH 列一并保留。

原 `PairedBootstrap` 的字段及 `difference()` 四个旧输出键不变，新增 `estimand_ids` 旁路属性分别
说明旧复合差 CI 和简单均值差 p 的身份。共享抽样求和辅助函数保留原算法；限定合成样本与冻结源码逐数组
精确比较。原九项历史 JSON 原字节复制，不重新执行旧历史统计。

新主要比较族固定为 G1 对 CASH、F5_MATCHED、G1_PASSIVE、SIMPLE_TREND，四项全部进入 Holm。
拟议历史评估固定 10,000 次、seed 20260910，复用现有 `automatic_block` 在已登记全列收益及平方序列
上取最大值、ceil 后限制在 `[2, n//4]`；至少四块是计算守卫，不是统计充分性保证。
半/双倍块长敏感性全部报告，不能选择最显著结果。当前历史抽样执行数为 0，四项结果为 null/NOT_COLLECTED。

`benchmark_factorial_attribution()` 只做平衡 2×3 表格的描述性分解：grand mean、信号主效应、
控制主效应及交互逐格重建平均 log growth。它不是回归拟合，也不证明因果 alpha。
缺少真实 PIT 市场因子和事前风险证据时，不输出伪造的 beta、截距或风险贡献。
同成交影子复用 `audit_cost_path` 的 quantity/time/side/reference/inventory 契约；缺真实新成交则 NOT_COLLECTED。

## 运行与交付

```powershell
.\.venv\Scripts\python.exe -m scripts.run_alpha_v5_benchmark_diagnostics --config configs/research/alpha_v5_benchmark_contract.yaml --preflight-dir <本批保全及实际测试记录目录>
```

运行前校验 main/HEAD、冻结来源 hash、零预算及当前源码对应的实际测试记录。独占目录和 journal 消耗一个
契约报告槽位，失败也保留并封存，不能删除重跑。源文件只读、报告只写新目录；封存包含旧文件备份、本批
implementation、diff、来源、报告、测试记录、完整 CASH 日历与不可变 manifest。

工程契约作业可以成功，真实研究验收仍不成立：B2 实际 PIT 缺件未解决、90 次历史矩阵未执行、固定数量
执行适配未完成，所有新统计/归因/执行证据均未收集。取得数据及相应范围授权后，必须在新的 generation
登记并执行；不得复用本 generation 填入后来的收益结果。

最终保持 **NO_PROVEN_ALPHA / CASH**，ML、纸面准入、实盘及订单提交全部关闭。
