# AegisQuant 下一批工程与量化研究整改方案

审阅日期：2026-09-09。性质：研究和工程方案，不是实施授权、交易建议或盈利承诺。

**当前结论：NO_PROVEN_ALPHA。生产继续 CASH；ML、纸面准入、实盘和订单提交保持关闭。**

## 0. 版本、实读范围与证据边界

首先读取了 `README_FIRST.md` 和 `VERSION_MAP.json`。随后通过已连接 GitHub 读取 main 分支元数据，以及指定提交的 `research/strategies/buffered_target.py`、`portfolio/risk_estimation.py`；在线 main 仍是 `d8c6d4013097f6323ab8b7a424c860ba0ccbd62b`。本次没有声称在线读遍整个仓库。其余源码审阅以包内 `repo/`、补丁和对应冻结 `implementation/` 为依据。

`changes_since_github_main.patch` 有 690 行，只覆盖 tracked 改动；R5 配置、PIT/registry、新入口、审计脚本、测试和工件等新增文件必须从 `repo/` 获取。对本轮六个主要文件，工作区副本与 R5 v3 冻结副本逐字节一致：`cat_replay.py`、`buffered_target.py`、`economic_gate.py`、`pit_universe.py`、`run_alpha_v5_research.py`、`audit_alpha_profitability_root_causes.py`。后文这六个文件的行号指本包 R5 版本，不能套用到远端 R4 文件。

### 0.1 路径约定

- `R5/` = `repo/artifacts/alpha_v5/20260908_research_churn_v3/`。
- `R4近期/` = `repo/artifacts/current_system_recent/20260908_v3/`。
- `SRC/` = `repo/src/aegisquant/`；`SCRIPTS/` = `repo/scripts/`。
- `CSV/` = 精简包根目录 `readable/`。
- 冻结实现的证据身份高于后来工作区同名源码。修订方案引用的“拟新增”文件不是现有事实。

| 结果 | 正确身份 | 时间与用途 | 不允许的解释 |
|---|---|---|---|
| R5 G1 | `alpha-r5-research-churn-20260908-v3`，本地未提交冻结实现 | 2022-04-01 至 2025-10-01，不含结束点；已使用历史开发诊断 | 不是最终盲测，不是已证明 alpha |
| 近期 R4 F3 | 冻结 R4 / `d8c6d401…` | 2026-03-08 至 2026-09-08 12:00 UTC；回顾性诊断 | 不含 G1，不可与 G1 拼接，也不是 G1 样本外 |

### 0.2 本轮独立完成与未完成

**完成：**运行包的 `VERIFY_BUNDLE.py`，2,465 个清单文件哈希全部匹配；对现有 CSV 的 17 个策略/成本组合核对共同日历、资金恒等式、季度复合和期末权益；对成交归因 CSV 的 3,181 行、11 个配置/成本组核对派生成交名义额及成本汇总。17 条路径期末与汇总差异为零；季度复合最大浮点残差约 `1.63e-14`，日资产负债恒等式最大残差约 `2.19e-11 USDT`。这些是只读算术核对，不是重新运行回测引擎。详见随附 `AegisQuant_Compact_Arithmetic_Audit_20260909.json`。

**没有完成：**没有完整包，因此不能独立核验原始 OHLCV 每行的来源、重复、缺口和聚合；不能从原始 order/fill/ledger JSON.gz 重建逐事件现金、持仓、费用、部分成交和撤单；不能逐行连接全部决策 Parquet 与实际订单；不能定位最差四小时当时的原始订单、盘口和每币共同冲击；没有重跑项目 1,188 项测试、55 次 R5 引擎回放或近期 180 场景。包中这些通过记录是保存证据，不是本轮执行记录。本轮新回测、模型拟合、校准拟合和最终留出访问均为零。

缺失完整包身份见 `FULL_EVIDENCE_REFERENCE.json`：

```text
AegisQuant_Review_20260909.zip
bytes = 260273857
sha256 = 43820627a6281cd2c2d197faea17da39ded6f9600210837aecbcfedc951264bb
file_count = 3362
```

完整包即使补齐，也不会自动补齐真实历史盘口、账户费率、全市场 PIT、完整独立试验史或真正未使用留出。不要把“本包省略的已有文件”和“项目从未取得的数据”混为一类。

## 1. 已证实问题与待验证假设

### 1.1 已证实的问题／证据事实

| ID | 已证实内容 | 具体证据 | 可作出的结论边界 |
|---|---|---|---|
| E01 | G1 五项换手验收通过，但统计及稳定性证据未通过 | `R5/report.md`、`root_cause_audit.json`、`paired_statistics.json`；`CSV/r5_quarterly_returns.csv` | 只证明这一开发路径上的工程与经济约束改善；不构成 alpha 证明 |
| E02 | G1 收益改善不能只归于省费，也不能把其余差额都称 alpha | `CSV/r5_all_strategy_summary.csv`；本轮算术核对 | 相对 F0 多出 16,060.45 USDT；账面成本减少 1,693.05，约占 10.54%；剩余主要是不同持仓／成交路径的账面差异，机制未识别 |
| E03 | 风险不是全面改善 | 同上及 `R5/root_cause_audit.json` | G1 最大回撤 16.82% 优于 F0 的 20.43%，但最差四小时 -6.10% 差于 -3.66%，四小时 CVaR95 也更差 |
| E04 | G1 普通风险调仓几乎消失，而且只有减仓没有恢复 | `CSV/r5_execution_reason_attribution.csv`；`R5/runs/G1/<symbol>/1` 对应 trial | 176 笔成交中普通调仓 12 笔，全部 `ORDINARY_RISK_REDUCE`；不能据此独立证明调仓被错误阻止 |
| E05 | PIT 组件存在，但真实选样未落地 | `repo/configs/research/aegis_alpha_v5.yaml`；`SRC/research/datasets/pit_universe.py:17–81`；`SCRIPTS/run_alpha_v5_research.py:305–422` | 实际仍为固定存活五币；流动性阈值为 null、membership manifest 为 null，组件测试不等于历史 PIT |
| E06 | 成本和规则仍是明确声明的代理 | `SRC/research/validation/cat_replay.py:254–341,425–447`；`SRC/portfolio/transition_costs.py:48–116` | 固定费用、NATR 滑点、线性参与率冲击、100,000ns 网络延迟不是账户或真实市场实证 |
| E07 | bar 撮合使用开盘参考价，同时按整根 bar 成交量限制成交 | `SRC/backtest/fills.py:29–72` | 这是 bar 级成交近似，不能证明开盘瞬间有四小时总流动性；不是已证实策略读取未来信号 |
| E08 | 组合模块已有，但 R5 主回放仍按币独立 sleeve | `SRC/portfolio/risk_estimation.py:32–90`；`optimizer.py:256–345`；`SCRIPTS/run_alpha_v5_research.py:305–370` | 缺口主要是接入和语义核对，不应另造整套组合引擎 |
| E09 | 容量与执行层对 impact 的函数形式不一致 | `SRC/portfolio/optimizer.py:155–165` 用 `(Imax/k)^2`；`SRC/backtest/costs.py:119–126` 用 `k*participation` | 前者隐含平方根冲击的反函数，后者为线性冲击；直接接线会使容量定义不一致，但当前 G1 没使用该组合优化器 |
| E10 | covariance 的输入校验不保证 PSD | `SRC/portfolio/risk_estimation.py:14–29`；`SRC/portfolio/models.py:97–128` | 对称且对角非负不足以排除负特征值；属于可通过固定反例证伪的契约缺口，不是 G1 已发生负方差 |
| E11 | 通用 split 的 purge 不覆盖所有中间边界 | `SRC/research/validation/splits.py:140–162` | train→validation 有 label-end 过滤；validation/calibration/test 的直接切片需要基于完整 episode 区间再次 purge。现有 `economic_filter.py:82–90` 另有边界守卫，不能据此指控已运行模型泄漏 |
| E12 | 当前 G1 没有均值估计不确定性 | `SRC/research/validation/cat_replay.py:686–687` 明确记录 None；`economic_filter.py:141–159,188` | 预测残差宽度不等于条件均值估计不确定性；不能伪造 OOF 或用残差标准差冒充均值标准误 |
| E13 | 统计工具已有，但完整研究历史不足 | `SRC/research/validation/statistics.py:70–98,113–149`；`experiment_registry.py:52–99`；`R5/paired_statistics.json` | DSR/PBO 应继续缺证据／null；55 个 sleeve 回放、180 个场景、1 万次 bootstrap 都不是独立策略搜索次数 |
| E14 | 当前统计表中 CI 与 p 值不是同一个 estimand | `SRC/research/validation/paired_bootstrap.py:24–40` | CI 是复合收益差，单侧 p 值来自均值收益差的居中零假设；必须分别命名，不能把正的未校正 CI 当成 Holm 已通过 |
| E15 | 没有已确认、可合法消耗的最终 ≥12 月未使用留出 | `VERSION_MAP.json`；R5 配置；`SRC/research/validation/persistent_holdout.py:14–54` | 2025Q4 原始文件尾部、看过的近期 R4 时段，均不能自动重新标成未知数据 |

试验定位示例：`alpha-r5-research-churn-20260908-v3:G1:BTCUSDT:1`。其他币和成本倍率按冻结 `preregistration.json` 的 `planned_run_ids` 查找，不从报告收益排名反推候选身份。

### 1.2 待验证假设，不作为既定故障

| ID | 假设与机制 | 当前依据 | 证伪方法 |
|---|---|---|---|
| H01 | 方差效用门槛叠加多个缓冲，导致普通调仓近乎冻结 | `buffered_target.py:243–259`、`cat_replay.py:568–622`；仅 12 次普通减仓 | 全部决策门槛漏斗＋固定效用算例＋三个一次一因素消融；不得直接调 λ 找盈利点 |
| H02 | 以平滑目标提出订单、用未平滑目标评价收益，会互相抵消 | `cat_replay.py:387–406,597–603` | 同一决策记录 raw/smoothed/proposed 三个目标，分别计算距离改变及拒绝原因；检查“朝平滑目标靠近、却偏离 raw”的比例 |
| H03 | 复核时钟与下单时钟共用，拒单或提交也可能推迟下一次正常复核 | `cat_replay.py:502–513,844–847`；配置明确 `ELAPSED_SINCE_LAST_REVIEW_OR_SUBMITTED_ORDER` | 拒单、partial fill、cancel/replace、pending、同时间事件的状态机测试；先确认这是冻结策略语义，而不是先擅改 |
| H04 | 最差四小时恶化主要来自更高／漂移的仓位与跨币共振 | G1 波动率及尾部指标；尚缺逐时持仓原始账本 | 对两策略所有最差 5% 四小时，逐事件分解每币库存 PnL、调仓、费用、共同 shock、事前风险估计 |
| H05 | 平滑器 gap 重置不足以证明全部指标已经重新就绪 | `cat_replay.py:395–402`；`test_no_future_mutation.py:85` | 跨 SMA/EMA、波动、流动性和 covariance 的连续历史守卫；不能只断言 gap 后 raw=smooth |
| H06 | 未来接入 L1/L2 时可能重复计 spread 或深度冲击 | `backtest/fills.py:75–170` 的 bid/ask/depth 参考价，`costs.py:128–132` 继续加 half-spread | MID 与 BBO/depth 两种显式价格基准的恒等 fixture；同一 spread 只应出现一次 |
| H07 | covariance 输入若已含总市场风险，再加因子会双算风险 | `risk_estimation.py:54–68` | 标明 TOTAL vs RESIDUAL；已知因子生成样本复核；不以更好回测决定是否加因子 |
| H08 | universe 同一 revision/time 冲突可能依赖输入顺序 | `research/datasets/universe.py:124–138` | 同键不同 payload 必须拒绝；随机重排原始 membership 后各历史快照哈希一致 |

## 2. 六个研究问题的具体处理

### 2.1 相同资金／风险／成本／日历：把 beta、省费与 alpha 拆开

#### A. 先保留四种不同层次的比较，不能混成一个排名

**原始经济账户视图。** 保留冻结初始总资金 50,000 USDT、五个 10,000 sleeve、无额外资金、原终止清仓约定。持续展示 CASH、F0/F3/F5、G1、G1_PASSIVE，既不按季度回到等权，也不免费跨币调钱。CASH 使用同一 USDT 计价；没有利息证据就按零名义收益，不能偷偷加入理财收益。在 USD/稳定币风险报告中另列 USDT 脱锚，不把 USDT 名义现金等同零信用风险。

**共同可交易风险预算视图。** 拟建同一个因果风险外壳，所有风险资产臂同初始现金、gross 上限、杠杆限制、事前 covariance 和波动上限、cluster、费用/规则、执行模型、容量与共同 UTC 日历。CASH 是零风险比较对象，不应强制它具有相同波动。对于不同信号，拥有相同风险约束并不意味着实现波动和持仓一定相同；两者都要报告。该外壳会改变持仓，因此结果命名 `MR_G1_V1`，绝不能覆盖或沿用“冻结 G1”的证据身份。

**2×3 机制矩阵。** 信号固定为 `{始终持有, 现有 10/40 趋势}`；普通仓位控制固定为 `{G0/F3, G1, 入场后数量固定但保留硬退出/硬上限}`。六个风险臂与 CASH 同跑。这样 F5 风格 passive、G1 passive、简单趋势和低调仓持有都有成对控制。F5 不是严格买入持有：`run_alpha_r4.py:313–316` 只是把趋势置真，风险/数据门槛及调仓仍存在。99% buy-and-hold 另列暴露参考，不冒称风险匹配基准。六臂不是六选一，而是用于分解信号、仓位控制及二者交互。

**beta 诊断视图。** 固定使用可重建的 PIT 市场因子及少量事前指定因子，报告净收益回归截距、beta、下行 beta、残差收益及区块区间。训练窗口拟合 beta、下一段评估；全样本回归仅标描述性。不能用全样本实现波动缩放成一个伪“可交易风险匹配”收益曲线。若因子本身不是 PIT，则截距只能是所选因子下的描述性残差，不能称全市场 alpha。

#### B. 账面恒等式与反事实必须分开

```text
Δ终值 = [G1 自己成交路径的账面毛损益 − F0 自己路径的账面毛损益]
        − [G1 账面成本 − F0 账面成本]
```

由现有汇总：

```text
G1 − F0 终值差                  = 16,060.4531157 USDT
F0 成本 − G1 成本               =  1,693.0537394 USDT
两条各自路径“终值加回成本”的差    = 14,367.3993763 USDT
```

第三项不是零成本且受资金约束的回放，亦不是 alpha。它包括多持仓、少持仓、趋势择时、路径漂移和成本反馈。必须再用“同成交影子成本”隔离直接费用变化，用成对 funded 回放研究间接行为变化。

还应明确代际桥接：F0 与 G1 不仅差一个 G1 门槛，F0 保留旧季度分段，而 G0/F3 已包含 R4 连续持仓与缓冲。因此 G1 新增机制的主要对照应是 G0/F3，F0 仅继续作为冻结churn验收基准。G1−G0 的终值差约12,985.48 USDT、账面成本差约729.69 USDT；同样不能直接把余额差称为新增alpha。复用已保存F0/F1/F2/F3的季度／连续与buffer矩阵解释旧代改动，不再把R4改进记到G1名下。

用共同时间索引比较净收益差 `d_t = log(1+r_candidate,t)-log(1+r_benchmark,t)` 可作为未来一个预登记主 estimand；分别输出长期增量增长率、置信区间和同一 estimand 的单侧 p 值。选择它必须在新结果产生前冻结，旧 mean/compound/Holm 结果完整保留，不能借换指标翻案。

每个 bootstrap 时间块同时抽取全部策略、币种与风险指标，保持市场同期相关性。今后主要比较族固定为候选对 CASH、风险匹配 F5、风险匹配 G1_PASSIVE、简单趋势，全部纳入 Holm。现有九项比较仍完整展示，不能只留下 G1−F0。自动块长规则、种子、抽样方式事前锁定；52 日规则的半/双倍块长只作预登记敏感性报告，不得挑产生显著性的块长。

#### C. 日历与 readiness

每条曲线要有真实现金空仓期间，不得删去“没有交易”的日期。主账户日历统一；诊断可增加共同 readiness 子区间，但必须同时展示全历与子区间及排除原因，防止重演 F4 的 readiness 混淆。日界权益采用同一时区、同一 `t` 前后事件顺序与费用结算 convention。

近期 R4 的末半日可以从完整日收益推断中排除，但完整资金报告必须保留该半日并做 reconciliation；不能从资金报告删掉末段以使统计表好看。季度边界、下一开盘付费退出、季度连续现金继承的老约定不得悄改。

### 2.2 真 PIT universe：缺的是历史事实和可知时间，不只是一个筛选函数

现有 `PointInTimeUniverse` 和 `eligible_universe_at` 应继续复用；缺口如下。

**历史资产身份。** 全部候选现货交易对的上市、交易开始、停牌、恢复、退市、迁移、换币/更名、计价币变更、同名重上市、交易状态、订单权限。必须包含退出过市场的资产。不能以今天 `exchangeInfo` 的符号列表回填 2022 年，也不能用“首根下载到的 K 线”当作已证实上市时点。

**公告与修订双时间。** 分开 `effective_from/to`、原始公告发布时间、修订发布时间、采集接收时间。已公告但尚未生效的退市可作为事前已知事件，不能提前把币从过去 universe 消失。后来更正的旧有效时点不能反写为过去已知。重建历史时，今天下载不代表历史一定不可知；但必须有存档发布证据，不能机械把 `available_time=event_time`。

**流动性与连续历史。** 30 日窗口必须严格截止 decision-time 可知的已收盘事件，使用真实 quote turnover 或逐笔求和；`base_volume*close` 不等于真实 quote turnover。完整 240 根 4h 只等于约 40 天，并不自动满足 160 日信号、协方差等最长窗口；每个组件分别要求其连续 warm-up，并取最大必要长度。未知缺口不得补零量继续视为完全可交易。

**规则身份。** `LOT_SIZE`、`MARKET_LOT_SIZE`、价格精度、最小/最大 notional、市场单适用条件、平均价格／参考价格规则都需要有效期和来源。Binance 官方文档列出了这些字段，但今天的规则文档不是历史快照。[R2]

**可证伪实现。** 对每个决策输出入选、排除、待证实全部集合以及原因、as-of snapshot hash、源证据 hash。同一输入随机排序不改变快照；同 revision 键冲突必须失败，而非“取最后一行”。PIT universe 只控制新开风险；资产突然不可交易时，已有持仓要保留和记账，不能将其删除、按最后好价免费退出或用未来退市价提前处置。

future-mutation 覆盖价格、volume、membership、listing/delisting、规则、fee schedule、L1/L2、特征修订、cross-asset normalization、fold/label 元数据。仅修改 cutoff 当时尚不可知（available_at > cutoff）的新增或修订信息，cutoff 前的特征、候选集合、风险估计、订单意图应逐字节不变。已经在 cutoff 前公开、只是将来才生效的公告属于已知前缀，不能修改它再要求历史决策不变；future-mutation 的边界按可知时间而不是仅按有效时间划分。订单发出之后的未来成交可随未来真实流动性改变，不应错误要求未来 fill 也不变。事后会计真值修订与“当时可知决策视图”需要分表，不能共用一次 as-of 查询。

### 2.3 G1 churn 改善：先验证是否变成了“少调整的风险暴露”

#### A. 冻结参数和实现链

保持现有全部参数：5 天 EWMA、48 小时复核、恢复/减仓半宽 20%/10%、绝对权重地板 3%、最小权重变化 3%、最小名义金额 50 USDT、lambda=1；H3/H10/R24/R72 和全部倍率结果保留，不择优。

普通调仓路径目前经过：raw风险目标与EWMA → 计算复核是否到期 → 经济门控（含原经济带宽） → 非对称数量缓冲 → 取整及最小金额 → 最小权重变化 → 方差效用/成本否决 → 最终通用数量调整。它不是单一“加了 10% buffer”。安全退出、趋势退出及硬上限在经济门控另有优先路径，不能因为普通调仓成本高就阻止安全退出；也不能在 pending 尚未协调时强行发重复卖单。

复核每层 `input_target / output_target / evaluated / veto_reason / superseded_by_hard_risk`。理由计数的分母必须同时包含决策数、订单意图数、订单数、fill 数，partial fill 不得被当作多次独立决策。

#### B. 风险效用量纲是首要核验项

实现为：

```text
B = max(0, ((w_current − w_raw)^2 − (w_proposed − w_raw)^2)
            × annual_vol^2 × review_years / 2)
允许普通调仓，当 C/NAV <= lambda × B，且其他门槛也通过。
```

这是权益归一化的短复核期方差追踪效用，不是预期收益，更不是可估计 alpha。示例仅作量纲验证：当前权重 0.40、raw 0.30、proposed 0.33、年化波动 0.60、两天期限，`B≈0.0000089692 NAV`；7% 权重交易若单边代理费用 16bps，则 `C≈0.000112 NAV`，为 B 的约 12.49 倍。这不是实际历史费率，亦不证明所有拒绝都错误，但足以说明“正常波动下极少调仓”可以由设计直接产生。

把期限设为 review interval 隐含“追踪误差只影响直到下次检查”；若实际拒绝会持续多次复核，其效用期限可能不一致。lambda 目前乘在收益侧，增大它会放宽而不是加严成本约束。必须先明确经济含义与单位，不能通过扩大 lambda 直到回测盈利。

#### C. 6/14、Holm 不显著、尾部变差各说明什么

G1 季度中位数约 -1.46%；主要正季度集中在 2023Q4、2024Q1/Q4、2025Q3。总收益可以由少数大涨阶段覆盖多个小亏阶段，6/14 本身不能证明趋势策略无效，但它不能满足稳定性要求，也不允许把季度门槛删掉。G1 约 611.5 天最长未修复回撤时长，与“持续稳定收益”有明显距离。

G1−F0 原始单侧 p≈0.01910，九比较 Holm 后≈0.17188；G1−G0 校正后≈0.20088；G1−F5≈0.55584，全部未过 0.05。1,280 个日权益点仅对应 1,279 个日收益；以 52 日块估算只有约 24.6 个块长的历史，1 万次抽样不创造新的市场历史。依赖性、少数行情驱动、候选相关和多次研究使用，使未校正的漂亮结果不足以晋级。[R4/R5 为多重搜索风险的原始方法依据，具体数值来自本包。]

尾部对比同时报告事前风险和实现风险：G1 平均暴露 22.86%，F0 19.98%；实现年化波动约 15.65% 对 12.44%；四小时 CVaR95 约 -0.8628% 对 -0.6967%。更低 MDD 不抵消更差单期损失。需检查尾部窗口开始前的 per-asset 数量、共同暴跌、资金集中、波动估计滞后、硬上限触发与成交可得性。精简包不足以将最差四小时归因到具体订单或市场事件。

#### D. 限定消融，不做搜索

未来单独授权后，最多三个一次一因素消融：仅关闭普通调仓效用否决、仅关闭 EWMA、仅取消普通复核冷却；其余参数与硬安全路径冻结。取消冷却的那一臂仍保留原 48 小时效用评价期限，防止同时改变两个因素。包括参考 G1，共 4 臂×5 币×3 个固定成本倍率=60 次 funded sleeve 回放。用途是证伪机制，不将最好收益者自动立为候选。

新增风险非劣性要求预先写清：除原五项 churn 外，普通风险改造不得将 `CVaR95_loss_4h` 或最差四小时损失幅度恶化超过 0.5 个百分点；这属于本方案新增的研究安全门槛，不是历史已授权门槛。G1 当前相对 F0 的最差四小时已超过该容差，应记录失败而非回头放宽。统计不确定时输出 INCONCLUSIVE；不能用“不显著变差”冒充已证明非劣。

### 2.4 执行校准：保留引擎，补真实输入和价格语义

#### A. 三种实验模式必须成为不可混淆的枚举

| 模式 | 固定什么 | 允许变化 | 正确验收 |
|---|---|---|---|
| REDECIDE_FUNDED | 策略规则、输入历史、初始资金 | 费用影响决策、现金、订单、成交、复利路径 | 资金守恒、因果性、比较经济表现；期末财富不要求随成本单调下降 |
| FROZEN_ORDERS_FUNDED | 原始订单意图 | 资金可行性、部分成交、拒单和库存 | 是固定订单，不是固定成交；同样不保证终值单调 |
| SAME_FILL_SHADOW | 成交时间、数量、方向、参考行情及库存路径 | 仅替换定义清楚的成本扣减 | 同一批成交，嵌套更差成本不能改善影子净损益；不声称资金可行或真实成交可实现 |

G1 的 1×、1.5×、2× 结果约 80,164.59、78,756.41、81,625.90 USDT，成交 176、171、167；这正需要行为路径分解，不能仅凭 2× 终值更高判会计错误。已有同成交影子 CSV/检查应复用，而不是新造另一套“固定成交”引擎。

#### B. effective fee 与 decision-time fee 分离

订单决策只用当时已知或预登记保守估计的费用；实际成交会计按成交有效时点真实规则和账户条件结算。保留 maker/taker、标准/特殊/税费、优惠适用对象、BNB 抵扣及余额不足回退、实际收费资产和汇率。Binance 官方明确其费率 FAQ 的示例数值是虚构示例；当前 commission API 也只证明当前账户条件，不能填充 2022 年真实费率。[R1]

`CostSchedule` 已有有效期，却没有完整“研究者何时可知”的证据字段（`backtest/models.py:359–390`）。采用兼容的 provenance 包装／引用，不把今天的 schedule 静默当作历史可知输入。无历史证据期间保留 `PROXY_ONLY`，在严格实证模式应失败，不以代理默认值自动降级通过。

#### C. spread / slippage / impact / latency 不重复收费

给 fill 增加 `reference_price_kind = MID | BBO | DEPTH_VWAP | BAR_OPEN_PROXY` 与 `included_cost_components`。MID 才需要完整半价差；BBO 已含跨 spread；DEPTH_VWAP 已含可见扫单深度，不再叠同一段深度冲击。额外 impact 只表示未纳入参考价的残余冲击，必须标明估计目标。`backtest/costs.py`、`transition_costs.py`、`optimizer._capacity_weight` 共用一个带 model_id、单位和 horizon 的纯 impact 函数及反函数。保留 LINEAR_PROXY_V1 复现旧结果；任何 SQRT/实证模型是新版本，不能在旧 schedule 下换公式。

执行数据必须区分决策、send、exchange receive/ack、撮合、用户流收到、cancel request/ack 等时间，量化时钟偏移和抖动。4h K 线不能辨别 100 微秒或 100 毫秒策略差异；没有实测延迟分布时只做明确标记的压力情景。未来公共 L1/L2 采集可以提高执行仿真精度，但不等于真实账户成交标定。Binance 的盘口 stream/更新协议是采集基础，不证明已有历史档案。[R3]

#### D. partial fill、participation 和容量

已有 bar、tradequote、L2 撮合及部分成交逻辑，应扩充 fixture 与真实数据适配。没有队列位置就不把“限价触及”当成必然 maker 成交；可先用保守 taker 实证研究，maker 标为未识别。未成交数量、订单寿命、撤改竞态和库存残余必须继续进入账本。

参与率分母要绑定执行 horizon 与真实市场累计成交量；不是整天 ADV、4h 成交量、单次盘口 depth 三者混用。所有同账户在同窗口的订单合并约束，买卖数量不可互相净额抵销来逃避参与率；盘口流动性同一事件不可被多个订单重复消费。

容量使用固定总资本阶梯 `1×/5×/10×/25×/50×`，基准 50,000 USDT，仅用于研究；不能线性缩放旧 PnL。报告成交率、拒单、清算所需时间、成本分位数、增量净收益及参与率违约。无深度/逐笔证据只能输出代理容量区间，不能给出“最大可交易金额”的确定结论。

拟订实证校准合格条件：独立校准验证段的费用/真实 fill 对账精确到币种最小记账精度；残余滑点按预先固定的 symbol/side/时段/参与率/波动桶审查；每桶至少 200 个可核验执行样本且覆盖至少 20 个交易日，否则合并预先定义的桶或返回样本不足；中位残差偏差绝对值不超过 1bp，预报 95% 不利成本分位数的实际超越率经日区块区间检查不得明显超过 10%。这些是拟议证据精度门槛，不是已达成结果。仅有公共逐笔时，验证的是撮合仿真，不冒称真实 API 实现偏差。

### 2.5 组合 covariance、共同尾部与风险容量：用现有模块接线

#### A. 修好契约再接入

`risk_estimation.py` 已具备 shrinkage/factor/regime；`optimizer.py` 已有波动、gross、group、capacity、turnover；`risk/engine.py`、`risk/stress.py` 也已存在。新增薄的多资产同步回放适配器，而不是新起 `portfolio_risk.py` 全套重复实现。

首先统一收益频率、币种排序、缺口处理、covariance 单位、as-of 可知时间。输入 TOTAL covariance 时不能再无条件加完整市场因子；输入 RESIDUAL 时才与已定义因子协方差相加。检验 PSD；只有浮点容差内的小负特征值可按固定规则修正并记录修正范数，明显不定矩阵失败关闭。不能临时增大 shrinkage 直到回测变好。

`[[1,2],[2,1]]` 特征值为 3 和 -1，是固定的对称/正对角反例；“某一组多头权重算出的 wΣw 为正”不足以通过 PSD 验收。

#### B. 组合目标与共享资金

在每个共同决策时点，先同步完整市场和账户事件，随后从已有 G1 得到 raw targets，再通过组合风险投影生成最终 targets。不把 binary trend 分数伪造为期望收益去喂均值优化器；可从已有 `_apply_group_caps` 等抽出纯目标投影函数，复用约束。

```python
# 伪代码：新一代研究适配器，绝不改冻结 R5 回放。
state = replay.consume_events_until(decision_time)
known = data_view.as_of(decision_time)
cov = covariance_from_closed_observations(known, frozen_policy)
validate_covariance(cov, require_psd=True, basis="TOTAL")
raw = frozen_signal_policy.targets(state, known)
safe = project_existing_targets(raw, covariance=cov,
                                limits=frozen_limits,
                                existing_positions=state.positions,
                                pending=state.pending_orders)
orders = ledger_aware_allocate(safe, state, fee_reserve=True)
assert_post_rounding_constraints(orders, state, frozen_limits)
replay.submit_research_orders(orders)
```

共享资金不等于免费再平衡：销售收入只能在成交和结算规则允许时用来买入。订单排序要按固定比例预算／确定性规则，交换币种输入顺序不得改变经济结果。pending 敞口与现金保留计入上限；dust、partial fill 后重新检查。组合硬降风险可绕过“普通调仓换手限额”，但不能绕过真实流动性和资金约束；风险超标又无法卖出时记录 BREACH/UNEXECUTABLE，禁止继续开风险，不伪造瞬间 CASH。

#### C. 第一版只冻结一份风险章程

下面是**待另行批准的唯一研究起点**，不是对旧结果的改写，也不是最优值；与已生效更严格限制冲突时取更严格值，语义无法比较则停止。

```yaml
portfolio_risk_proposal:
  return_frequency: UTC_DAILY
  lookback_calendar_days: 90
  ewma_half_life_days: 30
  diagonal_shrinkage: '0.20'
  covariance_basis: TOTAL
  factor_addition: DISABLED_FOR_TOTAL
  annualization_days: '365.25'
  volatility_target_annual: '0.12'
  leverage_max: '1.0'
  gross_max: '1.0'
  single_asset_max: '0.30'
  crypto_cluster_gross_max: '0.40'
  cvar_confidence: '0.95'
  cvar_loss_daily_max: '0.02'
  drawdown_window_days: 30
  drawdown_soft: '0.08'
  drawdown_hard: '0.12'
  ordinary_turnover_guard_must_not_block_hard_reduction: true
  enable_for_live: false
```

在五币同一 crypto cluster 情形中，以“cluster 风险贡献≤40%”约束整个唯一风险簇通常不可行：现金风险贡献为零，风险簇仍接近风险贡献的 100%。因此本起点明确采用 **cluster gross exposure ≤40%**；另外报告风险贡献，等有多个真正不同风险源时再研究贡献上限。不得在“名义敞口”和“方差/CVaR 风险贡献”之间混用 40%。

daily CVaR95 在 90 天只对应约 4–5 个样本尾部点，精度不足以单独证明安全。必须同时使用冻结历史联合情景、区块不确定性和保守压力约束；样本稀少时标 UNKNOWN，不用较小点估计自动提高仓位。30 日 drawdown 与全期 MDD 分开；硬门触发后的恢复必须有预登记迟滞和人工研究复核，不自动解锁生产。

#### D. 共同风险压力

复用 `run_portfolio_stress`：全币相关性接近 1 的联合下跌、连续 price gap、深度下降、滑点/延迟上升、交易所停摆、USDT 脱锚、同一时刻退出受阻。情景幅度事先登记，只称压力假设不称真实历史。BTC/ETH/BNB/SOL/XRP 均属加密风险，币数增加不等于独立尾部数量增加。

要单独解释组合尾损中价格因子、流动性、费用资产、场所和稳定币计价的贡献；比较原 independent sleeves、共享资金但同风险规则的桥接控制、以及共享资金＋组合风险投影，不能把资金共享收益当作风险控制 alpha。

### 2.6 ML：先造可审计实验，不先重训

#### A. 正确顺序

1. **现在先补 registry、split/label contracts 与 holdout 防火墙。** 恢复已有试验、失败、错误、剪枝、超时和人工修改记录；未知历史标 UNKNOWN。可完成纯合成测试，不拟合真实收益模型。
2. **补 PIT、执行、组合账本和 episode 标签。** 基础标签的交易机会、执行成本和风险目标不可信时，模型只能学到代理偏差。
3. **构造 purged OOF 预测与两类不确定性。** 在 outer-train 内完成，每个预测的模型不能见到该样本及其重叠标签终点。
4. **在 inner 验证内选择模型／校准／交易阈值；outer 只评估。** 时间块严格前推，跨币同时间归组，所有 scaler/缺失处理/特征选择/聚类/标签参数也必须 fold-local。
5. **锁定 nested walk-forward 和候选选择规则，完整生成 outer 结果。** 不因为某个 outer fold 亏损再调整特征或删币；旧历史仍叫研究级验证，不叫最终留出。
6. **检查完整 trial registry，计算有依据的 DSR/PBO 和校正比较。** 任何缺失不能填造；不能把这些统计量作为时间因果性或真实执行的替代品。
7. **冻结候选的代码、数据血缘、参数、风险、费用、规则、容量、统计定义与允许的定期训练程序。** 模型具体权重和模型更新时间也必须可审计；没有冻结更新程序则禁止测试期重训。
8. **最后才一次性读取已证明从未使用、至少连续 12 个月的 holdout。** 现在没有，不分配虚假路径；可规划未来封存或验证独立数据来源，但未批准前不运行。失败、不确定或数据读取异常都记录，已消费 claim 不因换 generation 重置。

Nested CV 的内层选择／外层评估能避免直接在评估集挑参数；scikit-learn 官方示例解释这一选择偏差，但时间序列不能照搬其随机 KFold。[R6] DSR 处理多重搜索与非正态，PBO 评估选择程序的过拟合风险；两者要求与实际搜索相符的输入，不会创造缺失历史或把重复使用开发集变成盲测。[R4][R5]

#### B. episode/meta-label 复用现有标签生成器

现有 `SRC/labels/generators.py:75–141` 已有可执行 t+1、双腿费用和 action-value；保留短期标签作为冻结诊断，不删除原失败模型。拟新增 `labels/episodes.py` 包装可执行基础趋势 episode：记录因果入场机会、风险/趋势退出、实际可知退出原因、事件起止、label 可用时间、毛净收益、MAE/MFE、成本和资本占用。

meta-label 回答“这个基础交易机会是否值得接受”，不重新预测每根 K 线方向。必须从**未过滤的基础机会集**产生所有候选，包含之后被 ML 拒绝的机会；不能只用已成交赢家训练。对被拒绝机会的收益只能来自冻结基础策略的反事实回放，标 COUNTERFACTUAL，不伪称实际赚到。风险退出独立于 ML，模型不确定不能 veto 减仓。

同一个长趋势中的多个决策和跨币同步 episode 不是独立样本。按完整 `[feature_dependency_start, label_end]` 建模依赖；purge 至少排除标签跨越任何验证／校准／测试边界者，额外 embargo 绑定执行/标签最大信息尾巴。不要只减去固定 12 根 bar 来处理持续数周的 episode。

#### C. 不确定性

- **预测分布**：未来交易收益本身的随机性，可用 purged OOF residual 分布、分位数及区间评估；不能只看训练残差。
- **均值估计不确定性**：有限训练集/模型选择导致的条件均值不稳定，可用只在训练期的时间块重采样重拟合等固定程序评估，记录重拟合预算。残差除以所有 K 线数量的平方根、模型之间方差、或反复换随机种子均不能自动替代它。

`economic_filter.py:82–90` 现有日期／label-end 检查要保留。`uncertainty.py` 的 conformal 辅助可复用，但必须添加 fold provenance 与时间依赖覆盖检验；不能无条件宣称非平稳市场中的精确覆盖。评价不只 AUC：Brier、log loss、校准、OOF 区间覆盖/宽度、接受率、错失正机会、避开负机会、增量净损益和尾部全记录。

当前派生表约 82 个 G1 入场 episode，不等于 82 个独立训练机会，更不支持把数千 bar 当成独立标签来训练大模型。数据不足时先完成协议和负控；模型可以是未来一个正则线性基准与一个有限浅树，不先上深网、在线强化学习或全自动搜索。

#### D. DSR/PBO 实现复核

`statistics.py:70–98` 的 DSR 输入需说明 Sharpe 频率、偏度/峰度口径、样本依赖、全搜索 trial 集及相关性处理。不同 cost scenario、fold、seed、币种、重复复现不是相同意义的独立候选次数；也不能因高度相关就把搜索次数减为 1。历史无法恢复时，报告可确认下界及敏感性区间，但正式证据仍 INSUFFICIENT。

`statistics.py:113–149` 的 PBO 目前按 segment mean 选择/排名；若实际候选选择用 Sharpe 或别的复合标准，必须采用同一预登记 score，否则在评估另一个选择算法。相同候选 tie 应用 mid-rank 或标不可辨识，不按数组位置产生虚假优劣。PBO 的组合分割是过拟合诊断，不是替代 causal walk-forward 的交易回测。

完整复现的 v1/v2 工程错误仍保留，但要区分“消耗计算槽位”和“已观察收益后影响搜索选择”；不能把未产生任何策略结果的 JSON 恢复错误虚构成独立收益候选。同样不能删除它们。

## 3. 优先级、代价与分批实施

### 3.1 总优先级

| 优先级 | 工作 | 修复机制 | 依赖／估计代价 | 主要风险 |
|---|---|---|---|---|
| P0 | 版本/证据契约、不可变原始工件、分离成本模式/统计量、G1 门槛审计 | 防止把不同策略、日历和证据等级混为 alpha | 精简包即可，约 2–4 工程日 | 写报告脚本误覆盖冻结结果；为通过检查改历史 |
| P0 | PIT 双时间与 future-mutation、规则/费率 provenance、holdout 防火墙 | 阻断未来信息和存活者选样晋级 | 契约约 4–7 日；真实数据采购/整理时间未知 | 缺数据时悄用今天列表或伪造可知时间 |
| P1 | G1 限定机制消融、共同风险基准与收益归因 | 区分省费、漂移、beta、信号增量 | 需完整原始账本和 prereg，约 3–6 日 | 把消融最好者事后选成冠军 |
| P1 | 真实执行校准及统一 impact/capacity 语义 | 使成本和资金可实现性有实证约束 | 约 5–10 日工程＋外部采集等待 | spread/impact 双计；使用未来总成交量冒充当前深度 |
| P1 | 现有组合风险模块接入共享账本 | 控制共同尾部、集中度、容量和资金竞争 | 上一批完成，约 5–8 日 | 资金共享和信号变化混淆；安全退出被换手限额挡住 |
| P2 | episode/OOF/nested ML/DSR/PBO 与候选冻结 | 使模型学习目标、选择和不确定性可审计 | 契约可提前；实证拟合需数据，约 5–10 日工程 | 过度样本化、校准泄漏、回头改 outer fold |
| P2 | 最终未使用 holdout／后续独立准入评审 | 检验冻结决策程序，不继续搜索 | ≥12 月真实未使用证据；时间无法用工程压缩 | 把旧尾部或近期报告重命名为盲测 |

工程日只是单人工作量估算，不包括数据许可、采集等待、额外研究授权，也不是交付时间承诺。P2 的接口/测试可并行前置，但真实 ML 拟合不能绕过 P0/P1 证据。

### 3.2 所有批次共用的规则

试验注册区分 `research_trial_id`、`engine_run_id`、`fit_id`、`cost_scenario_id`、`reproduction_id`，失败也记账。以下均为**未来提出的上限**，本轮不执行；新增候选、额外调参或预算耗尽都须新授权和新 generation，不可借“修复”无限重跑。只有专门证据审计和合成单元测试现在就能设计完成。

旧五项 churn 门槛保持：resize fill share≤50%、turnover≤F0 的60%、成本≤F0 的70%、CAGR 退化≤1pp、MDD 退化≤2pp。旧 v4 promotion 至少保留 Sharpe≥0.8、Calmar≥0.5、正收益 fold≥60%、中位 fold≥0、1.5×成本净收益>0、DSR≥0.95、PBO≤0.20、最大回撤≤25%、最少30闭合交易及其他配置门槛；全部字段从实际 SSOT 导入，不手工挑摘。

`deep-research-report.md:1176–1208` 还有更严格建议（如 MDD≤20%、单年利润占比≤35%、成本比≤35%）；与生效规则同一语义者可采用更严格门槛，不允许放松。`cost_to_gross_profit` 与 `cost_to_gross_alpha` 分母不是同一概念，不能简单替换数值；后者若 alpha 未证明或分母≤0应 UNDEFINED/FAIL。单年利润集中度门槛与仅12个月留出也需分窗口解释：不能在只覆盖一个年度的数据上机械要求利润年度占比≤35%，应保留原多年度研究门槛且将留出该项标证据不足，而非删除规则。

所有收益或显著性失败只是研究停止，不会由程序自动切换交易状态。统计功效不足须 INCONCLUSIVE；不得减小比较族、换指标、加试验或放宽门槛。

### B0｜证据及只读审计契约（P0，下一批首先做）

**文件／函数。** 新增 `research/validation/evidence_contract.py` 中 `load_evidence_manifest`、`validate_version_binding`、`check_calendar_contract`、`resolve_required_evidence`；新增薄入口 `scripts/audit_alpha_v5_evidence.py`，复用 `audit_alpha_profitability_root_causes.py` 的纯汇总逻辑但不调用其回放或旧输出路径；复用 `experiment_registry.py` 路径守卫及 `experiments/journal.py` 哈希链。

**工程测试。** 源哈希/版本错配拒绝；R4近期不准标 G1；日历重复/非UTC/缺日期报错；原始凭证缺失与 manifest 损坏不同状态；Decimal 解析无隐式 float；输出只能写新目录且 exclusive create；不能打开保护数据目录；原配置安全标志全 false；原 frozen 文件前后哈希完全一致。

**经济统计验收与对照。** 只复现已有 CSV 的终值、季度复合、费用恒等式和全部九比较标签；对照就是冻结原表，无新经济胜负检验。不得把汇总表通过推断为逐单通过。

**预算与停止。** 一次登记的只读报告任务；历史策略回放0、真实模型/校准拟合0、holdout访问0。任何错配失败并保留产物；同 generation 不重开 claim。

**产物。** `evidence_contract.json`、`evidence_gaps.json`、`arithmetic_audit.json`、`versions_and_safety.json`、`report.md`、测试日志和不可变输出 manifest。

### B1｜G1 机制与时钟语义审计（P0/P1）

**文件／函数。** 先给 `buffered_target.py:243–259` 的纯效用函数增加独立合成验证；审计脚本增加 `audit_resize_funnel`、`audit_review_clock`、`audit_tail_inventory`。新 trace 字段仅进新代次；老 G1 输出和行为不变。未来必须修改生产研究源码时，把普通调仓判定抽成纯函数 `evaluate_resize_candidate`，并以冻结端到端结果证明等价后才替换重复代码。

**工程测试。** raw/smooth 目标反向、zero vol、极小NAV、拒单、pending、partial/cancel race、gap、硬退出、硬上限、负/非有限数、两次取整幂等、min-notional 与 min-delta 组合、钟点边界与重复时间均有固定 fixture。不能通过取消 hard exit 来节约成本。

**经济验收与对照。** 先证明日志门槛漏斗覆盖全部决策，普通成交12且恢复0能从原始 trace→order→fill复原；尾部归因覆盖所有策略最差5%窗口而不是选择一个故事。后续三消融对照参考G1，原五churn与新增尾部非劣门槛同时报告；机制被证伪也算有效研究结果，不能据收益挑新候选。

**预算与停止。** 原始 trace 不在精简包，相关统计 NOT_VERIFIED，不伪造。未来单独授权后最多60次历史 sleeve 回放；三个消融一次性注册，不扩展网格。未能解释门槛顺序/资金差异，停止改参数。

**产物。** `resize_semantics.md`、`gate_funnel.parquet`、`clock_transition_cases.json`、`tail_attribution.parquet`；缺原始文件时先产出 schema、需要文件清单和固定合成案例。

### B2｜PIT 数据契约与 gap/future-mutation（P0）

**文件／函数。** 扩展 `datasets/universe.py::UniverseMembership` 的证据包装与同键冲突检查；`pit_universe.py::eligible_universe_at` 增加连续 warm-up 与流动性明细引用；`run_alpha_v5_research.py` 的新 generation 增加 PIT 模式入口，但保留 legacy 五币入口不变；扩展 `tests/alpha_v5/test_research_guards.py` 和 `test_no_future_mutation.py`。

**测试。** 上市前、公告后生效前、退市后、暂停/恢复、重上市、元数据晚到/修订、30日窗口边界、流动性零/缺失、短历史、gap恢复、跨币未来信息、输入行重排、同键冲突、symlink保护、未知规则下关闭新风险。删除一个今天不存活资产不能悄改旧市场集合；新增未来上市不能改过去快照。

**经济验收与对照。** 真实历史覆盖率、未知排除比例、全市场候选数、存活/退市覆盖透明；与 legacy 五币的成分差异报告只作偏差诊断，不按新表现挑资产。没有真实 PIT 文件时不可晋级。

**预算与停止。** 首批0历史收益回放，1次全量数据质量作业；资料有不可消歧的矛盾或审计覆盖不完整，严格模式失败。合成测试不冒充数据覆盖。

**产物。** `universe_events`、`liquidity_windows`、`rules_provenance`、`asof_snapshot_manifest`、`future_mutation_report`、数据缺口表。

### B3｜共同风险基准与归因（P1）

**文件／函数。** 新增薄入口 `scripts/run_alpha_v5_benchmark_diagnostics.py`；复用 `run_alpha_r4.py::run_sleeve` 的策略定义和既有 engine，不导入其默认冻结输出；扩展 `audit_alpha_profitability_root_causes.py` 的纯报告函数；统计仍使用 `paired_bootstrap.py`，新加明确 `estimand_id`，旧结果不改。

**测试。** CASH不交易、无风险期完整计入；相同 signal/control 配置产生完全相同订单/收益；时间、费用、terminal exit、common-ready标记一致；代码不得用全样本实现波动构造交易权重；所有臂使用同一风控和输入快照。共享资金阶段前仍以同结构独立 sleeve 控制；不能混合两种账户模式排名。

**经济统计验收。** 2×3六风险臂＋CASH；将信号主效应、控制主效应和交互分别列示；候选需在固定比较族对CASH、F5、G1_PASSIVE、简单趋势上有正增量且Holm通过，原生效门槛继续保留。回归截距只作补充，不取代真实可交易基准；不把失败比较删掉。

**预算与停止。** 6风险臂×5币×3倍率=90 sleeve回放；CASH为确定性账户曲线不额外搜索；旧冻结F5/99%buyhold只做引用。预登记4个主要比较，bootstrap10000，固定seed和块规则。混用风险/资金模式或样本不足则停止，不能新选最佳参数。

**产物。** `benchmark_contract.json`、全共同日历、风险/因子归因、同成交影子成本、四项主要比较和全部旧比较对照。

### B4｜有效时点执行实证与统一成本模型（P1）

**文件／函数。** 扩展 `backtest/models.py::FillSlice/CostSchedule` 的版本化引用，`backtest/fills.py` 的 event liquidity与queue状态，`costs.py::execution_price_and_cost`；在 `portfolio/transition_costs.py` 定义共用 impact 协议并让 `optimizer._capacity_weight` 调同一反函数。已有 `HistoricalCostBook`、`HistoricalRuleBook` 保留。

**测试。** MID/BBO/DEPTH价格桥接；分多笔成交费用资产记账；优惠失效/费率切换边界；maker不保证触碰成交；latency导致先后顺序改变；共享流动性消耗；整根bar未来量不可作为开盘可得量的实证声明；same-fill影子单调，funded不作单调断言；所有未成交残余都可追溯。

**经济验收与对照。** 旧 PROXY_V1 为 frozen对照；新实证模型用独立校准验证期检验前述费用精确对账、滑点偏差/分位数、partial fill和拒单预测。代理时期只能做敏感性，不可用“更保守”字样替代实证准确性。

**预算与停止。** 初次仅1份模型协议与1次校准数据切分；未来固定2个策略控制（G1和simpletrend）×5资本阶梯×3情景（基准、成本/延迟、深度/停摆）=30完整组合场景；同成交影子为配套算术，不新增候选。数据不覆盖高参与率区间则不得外推容量；残差不合格返回校准失败，不反复调模型直到该验证期过关。

**产物。** 时间戳/费率/盘口质量表、执行校准冻结manifest、残差分桶表、三种成本模式分离报告、容量曲线及未覆盖区间。

### B5｜组合风险接入及资金桥接（P1）

**文件／函数。** 给 `risk_estimation.py::estimate_covariance` 增加 TOTAL/RESIDUAL/PSD契约；复用 `optimizer.py` 的约束投影；新增 `research/validation/portfolio_replay.py` 薄适配器；复用 `risk/engine.py::evaluate_portfolio_proposal/evaluate_circuit_breakers` 与 `risk/stress.py::run_portfolio_stress`，不替换原引擎和 ledger。

**测试。** PSD反例、完美相关、资产重排、缺币/新币、零方差、资金竞争、卖出未成交先买入禁止、pending限额、post-rounding风险、partialfill后重算、hard-risk绕过普通turnover但不绕过流动性、venuehalt和depeg导致无法退出如实记录。

**经济验收与对照。** 三臂：原sleeve、共享资金桥接、共享资金＋单一冻结risk policy。必须拆出资金共享贡献；每期风险预算、预测/实现波动、cluster gross和risk contribution、CVaR与回撤持续时间均报告。风险改造需通过事前约束及尾部非劣，不把降低风险导致较低收益称失败后再调高风险；alpha晋级仍需原有所有门槛。

**预算与停止。** 3账户/风险模式×3固定联合压力路径=9组合回放，资本只用50k；资本阶梯复用B4产物，不额外挑容量点。多投影后约束不可同时满足时 fail-closed/保留真实持仓breach，不用无限迭代或删除最难约束。

**产物。** `portfolio_bridge_reconciliation`、covariance与风险预测、逐日riskcontribution、jointstress和breach账本、资金顺序不变性测试。

### B6｜ML 协议、OOF 与 nested 研究（P2；接口可先做，真实训练后批授权）

**文件／函数。** 新增 `labels/episodes.py`；扩展 `splits.py::walk_forward_splits` 与 `calendar_walkforward.py` 的所有边界 interval purge；给 `economic_filter.py::fit_economic_filter` 增加OOF输入/输出provenance，不删除旧调用；复用 `uncertainty.py`；新增薄入口 `scripts/run_alpha_v5_walkforward.py`；`statistics.py` 修补DSR输入契约和PBOscore/tie。

**测试。** 同episode不可跨fit/eval泄漏；全资产同时间组；val→calibration、calibration→test均purge；任何scaler/selector只fit innertrain；置乱未来标签不改过去OOF；模型fit异常耗费slot；模型不可用不妨碍riskexit；null历史不计算伪DSR/PBO；PBO数组重排不改变tie结果。

**经济统计验收。** 与同风险、同执行、无ML基础策略及恒定概率基准相比，OOF概率/区间至少不过度失准，净收益／尾部／机会账本不过度恶化；独立outer经Holm有增量、全部原门槛通过才允许候选冻结评审。AUC提高而经济增量不通过，仍失败。最低样本要求按有效episode与时间块记录，不用原校准器的30行触发视为统计充分。

**分割日期。** 若继续使用本包已用开发区间，预先固定三个完整、不遗漏尾部的outer评估块：`[2022-04-01,2023-06-01)`、`[2023-06-01,2024-08-01)`、`[2024-08-01,2025-10-01)`；每块14个日历月，训练从2021-01-01扩展至该块之前。各outer训练期最后9个月分三个顺序3个月inner验证块，各自只以前面的数据训练，并按真实label span purge。这样整段42个月均报告，不按已知好坏选季度。它仍是已使用历史的开发诊断。若真正PIT数据血缘或覆盖不同，应在任何fit前重新登记完整分割；不能边看结果边改变日期。

**拟议预算。** 当前真实fit=0。以后最多2个固定轻量模型规格×3outer folds×(3inner OOF fits+1outer refit)=24模型fit；均值不确定性最多每模型每outer20个训练区块重拟合，再120fit，总144；另6个最终校准fit。模型家族中心、校准法与阈值规则先冻结，不做超参网格；OOF用于内层选择的任何额外校准也必须计入预算，预算不足就采用预登记不校准控制而非偷偷拟合。上述120次重拟合只可用于其训练集之外的outer预测不确定性；不能把包含某个OOF样本的outer-train重拟合结果回填为该样本的OOF不确定性。若内层选择需要OOF均值不确定性，应事先另计每个purged训练子集的fit预算，否则该功能保持关闭。20次重采样若不足以稳定估计区间，报告不确定性未识别，不追加到“显著”为止。日后可另提更充足预算，但不能在该outer结果上修复晋级。

**停止。** 数据不足分3个有效outer、标签未成熟、purge后样本不足、历史trial不足或校准失准：只保留工程协议，停止实际ML推进。

**产物。** episode ledger、split manifest、OOF预测血缘、fit与calibration日志、完整trial registry、outer指标、DSR/PBO证据状态、候选冻结草案。

### B7｜一次性最终留出和独立评审（P2）

**文件／函数。** 复用 `persistent_holdout.py::open_persistent_holdout`、现有 freeze manifest和准入状态机；若缺入口，只新增薄wrapper，禁止再造另一套可重置计数器。

**测试。** 错hash/不满12月/已知已用/源尾部污染拒绝；claim在读取前持久化；loader失败也耗费claim；不同路径、symlink、重命名、另建generation不能重用同一语义数据；跨候选共享访问日志；不得通过缓存、预览、特征构建间接访问。

**经济统计验收。** 一次冻结候选及冻结比较族；所有既有门槛、共同风险基准、执行容量要求同时检查。失败或不确定都是NO_PROVEN_ALPHA；不回到holdout修特征。仅12月可能统计功效不足，不能因此放宽p值或稳定性门槛。

**预算。** 当前0；未来仅1次已授权的唯一data claim，不因失败重新取得同一数据。产物为immutable holdout report、access ledger、independent review；即使通过也只交独立准入评审，不自动开启订单。

## 4. 建议配置与数据 schema

以下是版本化扩展契约，未知字段用 null＋状态，不用默认数值冒充证据。金额/数量/率建议沿用项目 Decimal 字符串；时间为明确 UTC；所有引用必须有 hash。

### 4.1 证据与任务配置

```yaml
schema_version: aegis-review-contract-v1
generation: alpha-r5-review-contract-20260909-v1
status: PROPOSED_NOT_EXECUTED
branch_required: main
source:
  github_base: d8c6d4013097f6323ab8b7a424c860ba0ccbd62b
  local_patch_sha256: REQUIRED_FROM_INPUT
  frozen_implementation_manifest_sha256: REQUIRED_FROM_INPUT
scope: READ_ONLY_EVIDENCE_AND_SYNTHETIC_CONTRACT_TESTS
budgets:
  report_jobs: 1
  historical_strategy_engine_runs: 0
  real_return_model_fits: 0
  real_calibration_fits: 0
  final_holdout_accesses: 0
period_binding:
  r5_long: {strategy: G1, tier: PREVIOUSLY_USED_RETROSPECTIVE_DEVELOPMENT}
  recent_r4: {strategy: F3, tier: RETROSPECTIVE_DIAGNOSTIC}
forbidden:
  - STITCH_R4_AND_R5
  - PROMOTE_BEST_NEIGHBOR
  - WRITE_FROZEN_ARTIFACTS
  - READ_PROTECTED_HOLDOUT
  - AUTO_ENABLE_TRADING
production_policy: CASH
production_ml_enabled: false
paper_trading_admitted: false
live_trading: false
order_submission_enabled: false
```

### 4.2 数据表最小字段

| 表 | 必需字段 | 约束 |
|---|---|---|
| `evidence_item` | id,kind,path,sha256,bytes,source_version,strategy_id,period_start/end,tier,status,missing_reason | status枚举 VERIFIED/HASH_ONLY/DERIVED_ONLY/NOT_RECEIVED/NOT_COLLECTED/CONFLICT；未知不能PASS |
| `universe_event` | instrument_uid,symbol,venue,event_kind,effective_from/to,source_published_at,first_observed_at,revision_at,revision_id,available_at,availability_evidence_kind,source_hash | symbol不是永久身份；同事件同revision冲突拒绝；未知public发布时间不可伪填 |
| `liquidity_window` | instrument_uid,window_start/end,available_at,quote_turnover,quote_method,contiguous_bars,expected_bars,gap_count,source_hash,quality | 30日窗口严格；不把basevolume×close标EXACT；历史要求由实际依赖决定 |
| `fee_rule_provenance` | instrument_uid,account_scope,record_kind,effective_from/to,available_at,source_hash,verified_kind,payload_hash | decision-known与execution-effective分别索引；账户敏感信息脱敏，无需私钥 |
| `execution_observation` | order_id,fill_id,decision/send/ack/fill/receive/cancel_at,clock_error,side,qty,role,fee_asset/amount,reference_kind,reference_price,depth_sequence,participation_window,source_hash | 缺时间/队列位置明确unknown；fill唯一；部分成交累计≤订单量 |
| `resize_decision_audit` | decision_id,raw/smoothed/current/proposed/final_weight,vol/horizon,review_due,last_review/submitted/fill_at,each_gate_result,cost_fraction,benefit,rule_hash,pending_qty | hardrisk supersedes与ordinary路径区分；原始trace缺失不补虚构行 |
| `portfolio_risk_snapshot` | as_of,asset_order,return_frequency,covariance_basis,annualization,cov_hash,psd_status,raw/projected/postround_weights,forecast_vol,cvar/drawdown,cluster_kind,capacity_horizon,breaches | 上限与实现约束冲突有显式状态；风险贡献与gross不同字段 |
| `episode_label` | episode_id,base_policy_hash,instrument_uid,decision_at,feature_dependency_start,entry_at,label_end,label_available_at,net/gross_return,mae/mfe,exit_reason,cost_hash,actual_or_counterfactual | label只有在结束和成本可知后可用于fit；包含未被ML接受机会 |
| `oof_prediction` | prediction_id,episode_id,outer/inner_fold,model_fit_id,train_period/hash,purged_ids_hash,feature_pipeline_hash,prediction,distribution_interval,mean_uncertainty,status | 当前episode不在fit及重叠信息区；未知不确定性保留null |
| `trial_record` | research_trial_id,parent_id,generation,hypothesis,code/config/data_hash,selection_rule,registered_at,run/fit/scenario_ids,status,result_hash,observed_by_researcher,history_completeness | 失败、未产出结果、查看过收益分开；append-only，不杜撰独立性 |
| `holdout_access` | semantic_dataset_id,content/manifest_hash,start/end,prior_exposure_status,candidate_freeze_hash,claimed_at,loader_status,consumed | 跨路径/generation唯一；claim先于load；loader错误不退还访问 |

### 4.3 PIT 查询伪代码

```python
def decision_view(records, decision_time):
    # published/effective/revised 是不同时间；不可用今天最终版本直接回填。
    known = [r for r in records if r.available_at is not None
             and r.available_at <= decision_time]
    reject_conflicting_same_revision(known)
    event_revisions = latest_known_revision_per_event(known)
    state = apply_effective_events(event_revisions, at=decision_time)
    return state.with_hash_and_exclusion_reasons()


def eligible(symbol, decision_time):
    state = decision_view(universe_records[symbol], decision_time)
    liquidity = closed_contiguous_liquidity_window(symbol, decision_time)
    rules = decision_known_rules(symbol, decision_time)
    if not state.tradable or not rules.verified or not liquidity.complete:
        return EXCLUDE_NEW_RISK_WITH_REASON
    return liquidity.quote_turnover >= preregistered_threshold
```

这里 `verified` 是严格实证模式要求；legacy development 模式仍可使用显式proxy但证据等级不可提升。未来已公告的退出事件可加入事前风险处理，不应由 eligibility 直接丢弃未成交持仓。

### 4.4 统计接口局部 diff（仅新报告契约）

```diff
- {"ci_95": [...], "p_value": p, "passed": ...}
+ {"estimand_id": "DAILY_MEAN_RETURN_DIFFERENCE",
+  "p_value_one_sided": p, "correction": "HOLM",
+  "family_id": frozen_comparison_family_hash,
+  "family_size": 9,
+  "secondary_interval": {
+      "estimand_id": "COMPOUNDED_RETURN_DIFFERENCE",
+      "confidence": "0.95", "bounds": [...],
+      "multiplicity_adjusted": false},
+  "evidence_tier": "PREVIOUSLY_USED_DEVELOPMENT",
+  "promotion_authorization": false}
```

这是澄清旧统计定义，不重算或替换旧p值。新主estimand需要新的预登记，不能借字段修复回写历史“通过”。

## 5. 必须补充的外部数据与明确不能虚构的部分

| 数据 | 最低用途与覆盖 | 可接受证据 | 没有时的处理 |
|---|---|---|---|
| 完整包中的原始行级工件 | 复核本次已保存回测 | 符合完整包hash、逐单/决策/原始行情manifest | 原始逐单复核NOT_RECEIVED，先完成精简表审计 |
| 全历史上市/退市/停牌/迁移 | 真PIT选样，含失败/消失资产 | 有发布时间和有效时间的历史公告存档、历时快照、可审计历史数据商文件 | 固定五币仅开发诊断，不把今日列表补历史 |
| 历史quote量、连续OHLCV/逐笔 | 流动性窗口和gap验证 | 原始字段、交易所校验/下载manifest、聚合脚本和缺口日志 | basevolume×close仅proxy；不编造被退市币缺失价格 |
| 历史规则与账户费用 | 有效时点下单/成交结算 | 历时规则快照、已脱敏账户费用/成交单、有效优惠证据 | 当期已知估计与未知真实结算分别标记；不能用FAQ示例 |
| L1/L2、逐笔、序列连续性 | spread/深度/参与率/部分成交校准 | 合法获取的历史记录，或从批准日期起只读公共采集 | 不从4hK线合成“真实盘口”；只能做明确假设的压力 |
| 时间戳、网络/交易所延迟、真实fills | 实际实现差额与queue/撤单验证 | 用户已存在的脱敏历史日志；未来专门获批采集 | 公共数据只验证公共撮合近似；本任务不准试下实盘单 |
| 完整研究历史 | DSR/PBO与选择偏差 | 历史git/报告/配置/日志，人工变更也保留来源 | unknown不补试验，不把相关性/独立性杜撰成数字 |
| 至少12月真正未使用数据 | 唯一最终留出 | 独立访问审计、语义区间/血缘、冻结前无接触证明 | 当前NOT_ALLOCATED；等待新证据/未来封存，不重命名旧数据 |

外部资料使用/账户访问由用户另行授权。无需提供真实API私钥给审阅模型；不为校准执行质量发任何真实订单。历史数据商档案可用性、价格与覆盖需采购前核实，本方案不假定某供应商已提供完整历史。

## 6. 删除、合并与复用建议

**应立即复用而非重写：** `PointInTimeUniverse`／`eligible_universe_at`、`HistoricalCostBook/RuleBook`、EventBacktestEngine、既有Ledger、partialfill/L2机制、`estimate_covariance/build_portfolio_proposal`、risk stress/熔断、`ExperimentEventJournal/registered_run`、`persistent_holdout`、`paired_bootstrap` 与现有标签边界检查。它们已有较多守卫，缺口是输入真实度、接线和契约一致性。

**可以在新代次逐步合并：** 两套时间戳（last resize/review）用有命名的状态机接口统一，保留冻结语义；多层 min-notional/quantization 提取纯函数并测试幂等；impact 正反函数共用；报告统计和成本mode枚举统一；新oldregistry由一个adapter接入哈希链，不双写不同真值。未验证完全等价前不删旧实现。

**不能现在删：** 旧G0/F0/F5、A3/A7失败预测、H3/H10/R24/R72、1.5×/2×压力、v1/v2失败代次、原配置和源hash、同成交影子成本、未通过的统计比较。即使某些逻辑重复或性能较差，它们仍是研究自由度证据。

**暂不增加：** 新深度模型、RL、新闻/推文特征、新组合优化框架、另一个回测引擎、多套独立风控/留出状态机、无限贝叶斯参数搜索。不是判定这些方法永远无效，而是本轮它们会增加未知自由度，无法解决已定位的证据问题。

## 7. 直接交给 Codex 的下一批任务书

完整、范围收紧的执行文本另存 `AegisQuant_Codex_下一批任务书_20260909.md`。本次只建议实施 **B0＋B1的只读/合成契约部分**，不进入任何历史策略消融、真实ML拟合或holdout。

> 在现有 main 上保留所有用户未提交修改，以 `d8c6d401…`＋本地冻结R5v3证据为基准。先核对AGENTS、版本图、补丁、冻结manifest，安全可读失败就停止，不reset、不clean、不建分支、不推送。新建独立generation，仅实现精简证据只读审计、版本/日历/统计量/成本mode契约以及G1效用/时钟的合成测试与待验证清单。历史策略引擎回放0、真实模型和校准fit0、最终留出访问0、真实订单0。不得写R5/R4冻结目录，不改变G1参数和安全标志。输出所有失败、全部原比较、原始证据缺口、报告/测试和不可变manifest；最终仍为NO_PROVEN_ALPHA、CASH，不自动继续下一批。

## 8. 方法依据（本次访问官方/原始资料，2026-09-09）

本报告的项目结论依赖包内文件与上面列出的源码位置；以下资料用于外部协议和方法依据，不是项目已拥有对应数据的证明。URL 放在代码形式，便于归档复核。

- [R1] Binance Spot Commission Rates FAQ。官方明确区分实际账户费率与文档示例，并说明手续费类型／币种。`https://developers.binance.com/en/docs/products/spot/faqs/commission_faq`
- [R2] Binance Spot Filters。数量、市场单数量、名义金额、价格等规则的官方定义。`https://developers.binance.com/en/docs/products/spot/filters`
- [R3] Binance Spot WebSocket Streams。公共市场数据的官方流协议。`https://developers.binance.com/en/docs/products/spot/web-socket-streams`
- [R4] Bailey & López de Prado，2014，The Deflated Sharpe Ratio，作者原文。仅支持搜索偏差/非正态调整的方法依据，不证明本项目DSR数值。`https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf`
- [R5] Bailey, Borwein, López de Prado & Zhu，The Probability of Backtest Overfitting，作者机构出版页。`https://scholarworks.wmich.edu/math_pubs/42/`
- [R6] scikit-learn 官方 Nested versus non-nested cross-validation。用于选择与评估分层原理，时序任务另需因果purge/embargo。`https://scikit-learn.org/stable/auto_examples/model_selection/plot_nested_cross_validation_iris.html`

**最终判断：优先把已经实现的系统变成可解释、可比较、可追溯、可否定的实验，而不是继续增加信号或挑历史最优。当前 NO_PROVEN_ALPHA 是正确结论，可以在整改后继续保持。**
