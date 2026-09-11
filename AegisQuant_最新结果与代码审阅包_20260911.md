# AegisQuant 最新结果与代码审阅包

编制日期：2026-09-11（Asia/Shanghai）。用途：将此一个 Markdown 文件上传给网页版 ChatGPT 6 Pro，进行独立问题查找、优化方案评审和下一批任务设计。

**当前结论：NO_PROVEN_ALPHA；生产保持 CASH，模型、纸面、实盘、订单全部关闭。当前工作树全仓测试为 1,488 通过、2 失败，不能描述为全仓验证通过。**

## 给外部评审模型的任务

请先核对版本、会计恒等式、信息可知时间、统计量及实际验证范围，再提出改进。按严重程度输出问题，逐条列出证据路径/符号/行号、触发条件、影响、最小修复及必要验证；明确区分已证实的问题、合理怀疑和缺失数据。优先处理本轮两个测试失败、风险模块边界、PIT/执行数据、完整调仓漏斗与联合尾部风险。请提出少量可验收的下一批工作，分别列出可立即进行的工程修改和必须先获得数据/独立研究授权的实证。不要把历史正收益、成本下降、合成测试通过或未校正显著性当作交易准入；不要根据已看过的开发结果挑选新赢家。不能从本文件证明的事项，请给出确切所需文件/字段/数据区间，不要编造结果。

本次交付范围是清理缓存、发布现有版本和整理审阅材料。两个集成失败及格式问题原样保留供审阅；本次没有修改策略、风控或测试断言，也没有进行新的历史策略回放、真实拟合、最终留出或下单。

## 版本身份和阅读口径

- 仓库：[https://github.com/tORHANSxd/AegisQuant](https://github.com/tORHANSxd/AegisQuant)；发布分支 `main`。
- 本次整理前的父提交：`d8c6d4013097f6323ab8b7a424c860ba0ccbd62b`。该值是旧基线，不能当作本次发布的完整源码身份。
- 当前 `src/`、`scripts/`、`configs/`、`tests/` 共 825 个可版本化文件的内容集合 SHA-256：`f9002abdef454eb8aa86b9bf808743fc9b5541de0397062a22c0db445f50e5a3`。算法为排序路径→文件 SHA-256 的 UTF-8 紧凑 JSON 再取 SHA-256；包含测试，排除本报告和冻结副本。这不是 Git tree ID。
- 本报告随本次 main 提交发布，最终提交号以 GitHub 的本文件提交历史为准。下方关键源文件各有字节哈希及行号，便于脱离仓库核对。
- 工程与安全 SSOT：[AegisQuant_盈利导向重构任务书_v4.md](https://github.com/tORHANSxd/AegisQuant/blob/main/AegisQuant_%E7%9B%88%E5%88%A9%E5%AF%BC%E5%90%91%E9%87%8D%E6%9E%84%E4%BB%BB%E5%8A%A1%E4%B9%A6_v4.md)。后续研究任务书为 [deep-research-report.md](https://github.com/tORHANSxd/AegisQuant/blob/main/deep-research-report.md) 和 [AegisQuant_整改与验证方案_20260909.md](https://github.com/tORHANSxd/AegisQuant/blob/main/AegisQuant_%E6%95%B4%E6%94%B9%E4%B8%8E%E9%AA%8C%E8%AF%81%E6%96%B9%E6%A1%88_20260909.md)；B0–B7 指此次整改工程阶段，不能混同旧 v4 的同名策略臂。

| 材料 | 实际含义 | 不可据此推出 |
|---|---|---|
| R5 research_churn_v3 | 2022-04-01 至 2025-10-01 固定存活五币、无 ML 开发诊断 | 当前所有新代码已经生成相同业绩；真实 PIT；最终留出通过 |
| recent 20260908_v3 | 2026-03-08 至 2026-09-08 的冻结 R4 F3 等连续策略 | G1 最近六个月收益；未使用的 12 个月最终留出 |
| B0–B7 合约输出 | 工程接口、只读已有证据、合成数据及纯函数验证 | 已完成新六臂真实回放、ML/校准、共享资金或执行实证 |
| saved_evidence_v2 | 215 个旧模拟记录的 trace/order/fill/ledger/MTM 对账 | 真实交易所执行已验证；因果因子归因；新统计显著性 |

旧报告仍保留其当时状态；例如 B0/B7 中原始记录未验证的缺口，后来仅在 saved_evidence_v2 的明确覆盖范围内得到补充。当前新代码、当时冻结代码和只读核验代码是不同身份。

## 本次确认的问题与优先审阅项

| 优先级 | 事实及证据 | 影响与下一步判断 |
|---|---|---|
| P1 | `tests/architecture/test_risk_boundaries.py:34` 失败；`research/validation/portfolio_replay.py:67–79` 直接导入 5 个 `aegisquant.risk.*` 模块 | 与现有研究/模型不得导入独立风控的架构契约冲突。桥接虽宣称只生成提案，仍应核对模块归属及依赖方向；不能仅删测试或放开保护。 |
| P1 | `tests/alpha_v5/test_resize_semantics_contract.py:37` 的整文件冻结哈希断言失败 | 差异实际在 `portfolio/optimizer.py`；`buffered_target.py` 与 R5 冻结副本字节相同，`target_quantity_adjustment` 的 AST 也与冻结副本相同。需明确“整个模块身份”与“被调用纯函数等价”的契约，并保持历史来源证明。整文件失败目前仍真实存在。 |
| P1 | G1 只有 6/14 季度盈利、9 项 Holm 校正全部未过 0.05；最差 4h 为 -6.10% | 不能以 CAGR、Sharpe 或换手改善替代经济与统计准入；需要评估收益是否只是市场暴露/时段/风险配置。 |
| P1 | 真实 PIT、费用/规则/盘口/延迟、完整独立试验史、未使用留出缺失 | 工程可运行不等于研究已具备有效性；B2 明确 fail closed。先列所需字段和来源，不能以今日币表或合成样本填空。 |
| P2 | 保存 trace 只含终态门槛理由，缺少全部内部门槛及 veto 前/二次取整后完整目标 | 652,205 行终态漏斗不等于逐门槛因果归因；需要未来独立 generation 的完整记录方案。 |
| P2 | `scripts/run_alpha_v4_final_holdout.py` 全仓格式检查失败，与本轮开始时 HEAD 相同 | 既有格式债务；未改变语义或旧证据。不要把 lint 与 format、纯测试与完整 CI 混为一谈。 |

以上 P1/P2 是审阅优先级，不是已认定存在可利用漏洞。架构违例和失败断言已由真实测试证实；收益来源及实证充分性的判断必须依赖后续证据。

## 最新 G1 冻结历史结果

研究区间 `[2022-04-01, 2025-10-01)`；BTC/ETH/BNB/SOL/XRP 各 10,000 USDT，共 50,000；独立 sleeve，无跨币转资。策略为 4h LONG/FLAT 低频趋势与风险仓位，G1 再加入 5 天 EWMA 平滑、48 小时复核、加/减仓相对半宽 20%/10%、3% 绝对缓冲和最小权重变动、50 USDT 最小调仓。硬退出与上限可以绕过普通调仓成本收益门槛。

| 配置 | 成本 | 期末净值 USDT | CAGR | Sharpe | 最大回撤 | 成本 USDT | 成交 | resize 占比 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| F0 | 1× | 64,104.14 | 7.35% | 0.633 | 20.43% | 2,912.38 | 2022 | 89.7% |
| F3 | 1× | 67,179.11 | 8.80% | 0.736 | 19.18% | 1,949.02 | 1905 | 91.4% |
| F5 | 1× | 81,031.84 | 14.78% | 0.790 | 26.40% | 2,096.44 | 3682 | 99.7% |
| G1 | 1× | 80,164.59 | 14.43% | 0.940 | 16.82% | 1,219.33 | 176 | 6.8% |
| G1 | 1.5× | 78,756.41 | 13.85% | 0.899 | 18.57% | 1,806.66 | 171 | 4.1% |
| G1 | 2× | 81,625.90 | 15.02% | 0.895 | 18.37% | 2,451.84 | 167 | 1.8% |
| G1_H10 | 1× | 80,186.98 | 14.44% | 0.956 | 16.82% | 1,216.83 | 184 | 10.9% |
| G1_H3 | 1× | 79,378.23 | 14.11% | 0.930 | 16.82% | 1,214.53 | 175 | 6.3% |
| G1_PASSIVE | 1× | 66,602.33 | 8.53% | 0.605 | 23.62% | 86.31 | 19 | 47.4% |
| G1_PASSIVE | 1.5× | 67,442.16 | 8.92% | 0.610 | 23.63% | 130.02 | 16 | 37.5% |
| G1_PASSIVE | 2× | 70,926.80 | 10.50% | 0.667 | 24.34% | 186.28 | 12 | 16.7% |
| G1_R24 | 1× | 80,565.00 | 14.59% | 0.907 | 18.41% | 1,217.56 | 167 | 1.8% |
| G1_R72 | 1× | 77,782.56 | 13.45% | 0.926 | 16.82% | 1,198.64 | 189 | 13.2% |


相对 F0，G1 成交名义额减少 **58.54%**、实际成本减少 **58.13%**；五项 churn 门槛通过。G1 1× 普通减仓 12 笔、普通恢复 0 笔，普通调仓占全部 176 笔成交的约 6.8%。CAGR 增加 7.08 个百分点，最大回撤下降 3.61 个百分点；但 14 季度仅 6 个盈利，中位季度收益 -1.46%，F5 期末财富仍比 G1 高 867.25 USDT，G1 最差四小时 -6.10%（F0 -3.66%）。“少交易、省费用”在该历史中成立，“已有可靠 Alpha”不成立。

成本收益量是权益归一化的方差偏离损失下降：

`max(0, ((w_current-w_raw)^2 - (w_proposed-w_raw)^2) × annual_vol^2 × review_years / 2)`。

它与舍入后增量执行成本/权益进行比较，是风险效用代理，不是未来收益预测。更高成本会改变拒单、可用现金和后续成交路径，因此资金约束的 2× 场景终值可以高于 1×；同成交影子成本另行保持成本单调性，不能混用这两种结果。

冻结预登记统计原值如下：共同日历、52 天区块、10,000 次 bootstrap，9 项比较统一 Holm 校正。请核对旧协议的复合收益差区间与单侧检验统计量是否对齐；后续 B3 的 log-growth 接口改进尚未产生新的历史统计结果。


~~~~json
{
  "evidence_tier": "DEVELOPMENT_UNCERTAINTY_ONLY",
  "block_days": 52,
  "comparisons": {
    "G1-G0": {
      "observed_compound_return_difference": 0.25970963150219656,
      "ci95_lower": 0.0171237045221357,
      "ci95_upper": 0.9249095029129479,
      "one_sided_mean_p_value": 0.028697130286971302,
      "terminal_wealth_difference_usdt": 12985.481575109909,
      "holm_adjusted_p_value": 0.20087991200879912
    },
    "G1-F0": {
      "observed_compound_return_difference": 0.32120906231416496,
      "ci95_lower": 0.04586509569931174,
      "ci95_upper": 1.0752264824339488,
      "one_sided_mean_p_value": 0.019098090190980903,
      "terminal_wealth_difference_usdt": 16060.453115708311,
      "holm_adjusted_p_value": 0.17188281171882813
    },
    "G1-F5": {
      "observed_compound_return_difference": -0.017344944793440176,
      "ci95_lower": -1.1870917197650352,
      "ci95_upper": 0.7947261012732433,
      "one_sided_mean_p_value": 0.5558444155584441,
      "terminal_wealth_difference_usdt": -867.2472396717203,
      "holm_adjusted_p_value": 0.5558444155584441
    },
    "G1-G1_PASSIVE": {
      "observed_compound_return_difference": 0.2712452473070123,
      "ci95_lower": -0.3688238997037245,
      "ci95_upper": 1.2599588186764583,
      "one_sided_mean_p_value": 0.205979402059794,
      "terminal_wealth_difference_usdt": 13562.262365350616,
      "holm_adjusted_p_value": 0.411958804119588
    },
    "G1-CASH": {
      "observed_compound_return_difference": 0.6032918304592945,
      "ci95_lower": -0.16422783332174046,
      "ci95_upper": 2.2888449472584456,
      "one_sided_mean_p_value": 0.07479252074792521,
      "terminal_wealth_difference_usdt": 30164.591522964794,
      "holm_adjusted_p_value": 0.22437756224377564
    },
    "G1_H3-G0": {
      "observed_compound_return_difference": 0.24398234784508893,
      "ci95_lower": 0.013974673007877404,
      "ci95_upper": 0.8694278177923079,
      "one_sided_mean_p_value": 0.030596940305969402,
      "terminal_wealth_difference_usdt": 12199.117392254338,
      "holm_adjusted_p_value": 0.20087991200879912
    },
    "G1_H10-G0": {
      "observed_compound_return_difference": 0.2601574058847132,
      "ci95_lower": 0.02323854166182963,
      "ci95_upper": 0.8910853903169041,
      "one_sided_mean_p_value": 0.0244975502449755,
      "terminal_wealth_difference_usdt": 13007.870294235734,
      "holm_adjusted_p_value": 0.195980401959804
    },
    "G1_R24-G0": {
      "observed_compound_return_difference": 0.2677177222832788,
      "ci95_lower": 0.0017184429442271714,
      "ci95_upper": 1.0153474119363775,
      "one_sided_mean_p_value": 0.0375962403759624,
      "terminal_wealth_difference_usdt": 13385.886114163892,
      "holm_adjusted_p_value": 0.20087991200879912
    },
    "G1_R72-G0": {
      "observed_compound_return_difference": 0.21206908719323742,
      "ci95_lower": -0.0023848888784200654,
      "ci95_upper": 0.7468289827440787,
      "one_sided_mean_p_value": 0.03519648035196481,
      "terminal_wealth_difference_usdt": 10603.454359661817,
      "holm_adjusted_p_value": 0.20087991200879912
    }
  },
  "dsr": null,
  "pbo": null,
  "dsr_pbo_status": "INSUFFICIENT_COMPLETE_HISTORICAL_INDEPENDENT_TRIAL_HISTORY"
}
~~~~

## 最近六个月结果的准确身份

近期数据截至 2026-09-08T12:00:00Z，评估从 2026-03-08T00:00:00Z 开始；该报告对应冻结 **R4 F3**，G1 近期结果状态仍为 **NOT_COLLECTED**。末端付费退出参考为 2026-09-08T08:00:00Z，最后 4 小时保持现金，没有使用数据末端之后的价格。

| 配置 | 净收益 | 期末USDT | 最大回撤 | 年化Sharpe | 平均资金暴露 | 闭合交易 | 胜率 | 总成本USDT |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 当前生产：现金 | 0.00% | 50,000.00 | 0.00% | — | 0.00% | 0 | — | 0.00 |
| 连续趋势、无缓冲 | 6.75% | 53,376.33 | 6.68% | 1.23 | 19.26% | 15 | 33.33% | 456.74 |
| R4 主候选：连续趋势＋10%缓冲 | 6.07% | 53,035.49 | 6.59% | 1.16 | 18.90% | 15 | 33.33% | 362.02 |
| 固定多周期趋势 | 2.83% | 51,413.42 | 3.45% | 1.01 | 8.84% | 15 | 26.67% | 161.23 |
| 同风险政策持有 | 10.02% | 55,011.42 | 14.32% | 1.04 | 49.02% | 5 | 100.00% | 302.90 |
| 买入持有（原 B1，99%目标） | 18.42% | 59,210.26 | 28.02% | 1.00 | 98.88% | 5 | 100.00% | 166.76 |


F3 全段盈利 3,035.49 USDT，8 月单月盈利 4,161.88 USDT，利润集中；5 项预登记比较的 Holm p 全为 1.0。180 个实际场景另由冻结源码完整复现 180 次。不能把这份报告称为 G1 最近半年表现，也不能称为满 12 个月事前封存留出。

## B0–B7 工程交付及完整研究缺口

| 阶段 | 最新 generation 目录 | 已完成 | 仍未完成 |
|---|---|---|---|
| B0/B1 | `20260909_review_contract_v2` | 只读证据/时间、成本与调仓语义合同；保留失败链 | 原始记录缺口后来由 saved_evidence_v2 部分补齐；近期 G1 未采集 |
| B2 | `20260910_pit_contract_v1` | PIT 可知时间、完整性和失败关闭接口 | 真实四类 PIT 输入均未收到，FAILED_CLOSED_INSUFFICIENT_PIT_EVIDENCE |
| B3 | `20260910_benchmark_contract_v1` | 六风险臂/CASH/路径和配对统计契约 | 新真实六臂矩阵、归因、四项统计、影子成本未采集 |
| B4 | `20260910_execution_contract_v1` | 显式成交价、费用原币、余额回退、参与率和校准协议 | 真实历史费率、盘口顺序、延迟、排队与校准残差未采集 |
| B5 | `20260910_portfolio_contract_v1` | 协方差/共享资金提案桥接、风险与资金约束的合成验证 | 真实共享账本回放、联合尾部、容量未完成；本轮发现架构导入测试失败 |
| B6 | `20260910_ml_contract_v1` | 完整机会 episode、严格分割、OOF/拟合元数据接口 | 真实训练、校准、OOF/outer 指标均为零，日期块不是有效独立统计折 |
| B7 | `20260910_final_contract_v1` | 一次性访问、claim/freeze/hash/独立复核合同 | 未创建真实锚点，未读取真实留出，不满足完整研究验收 |

这些新合同工作的真实历史策略回放、真实收益模型拟合、真实校准拟合、最终留出访问、真实订单五项均为 0。历史 R5/R4 已发生的回放次数不因此变成 0；纯测试可能使用合成数据和临时账本，它们不是新增真实金融实验。旧 v4 固定拟合与重建有各自历史身份。

缺口包括：历史上市/退市与修订可知时间；截至决策时可知的 30 日流动性与规则来源；账户历史费率及原币费用余额/汇率；带时序的 L1/L2、成交、ack/cancel/queue 和客户端/场所延迟；真实共享现金、pending、settlement 与成熟未过滤机会集合；完整独立试验历史；冻结的模型/校准选择规则及独立拟合授权；此前未使用的连续至少 12 个月数据与独立存储/复核。当前零预算合同配置不是后续研究授权，也不能将真实留出当日常测试输入。

## 最新已保存模拟记录核验

状态 `VERIFIED_STORED_SIMULATION`：215 个保存运行、16,685 笔成交、16,900 条账本记录、652,205 行 trace、652,635 个原始 MTM 点。逐 run 核验与原 R5 派生表对照失败数均为 0。下表以倍率 cost 分组；费用金额使用独立字段 paid_cost。原 v1 同名字段覆盖导致错误按金额分组，v1 全目录及问题记录保留。

| 策略 | 成本倍率 | 保存运行 | 成交 | trace 行 | 原始 MTM | 普通减仓 | 普通恢复 | 最差 5% 窗口 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| F0 | 1 | 70 | 2022 | 38365 | 38505 | 890 | 924 | 384 |
| F1 | 1 | 70 | 1915 | 38365 | 38505 | 882 | 825 | 384 |
| F2 | 1 | 5 | 2002 | 38365 | 38375 | 901 | 937 | 384 |
| F3 | 1 | 5 | 1905 | 38365 | 38375 | 890 | 851 | 384 |
| F4 | 1 | 5 | 1978 | 38365 | 38375 | 937 | 953 | 384 |
| F5 | 1 | 5 | 3682 | 38365 | 38375 | 1823 | 1849 | 384 |
| G0 | 1 | 5 | 1905 | 38365 | 38375 | 890 | 851 | 384 |
| G1 | 1 | 5 | 176 | 38365 | 38375 | 12 | 0 | 384 |
| G1 | 1.5 | 5 | 171 | 38365 | 38375 | 7 | 0 | 384 |
| G1 | 2 | 5 | 167 | 38365 | 38375 | 3 | 0 | 384 |
| G1_H10 | 1 | 5 | 184 | 38365 | 38375 | 20 | 0 | 384 |
| G1_H3 | 1 | 5 | 175 | 38365 | 38375 | 11 | 0 | 384 |
| G1_PASSIVE | 1 | 5 | 19 | 38365 | 38375 | 9 | 0 | 384 |
| G1_PASSIVE | 1.5 | 5 | 16 | 38365 | 38375 | 6 | 0 | 384 |
| G1_PASSIVE | 2 | 5 | 12 | 38365 | 38375 | 2 | 0 | 384 |
| G1_R24 | 1 | 5 | 167 | 38365 | 38375 | 3 | 0 | 384 |
| G1_R72 | 1 | 5 | 189 | 38365 | 38375 | 25 | 0 | 384 |

17 组各有 7,674 个四小时收益窗口，最差 ceil(5%×N) 各 384 个，临界值并列全部保留；共 6,528 窗口、32,640 条五币贡献记录。所有窗口现金与持仓市值变化、原生数量×已知标记价、组合贡献加总及时间边界核对通过。季度边界保留已付退出成本，不能从重置后的资金拼接遗漏亏损。

保存标记前填中，有 85 个已报告的标记年龄超过四小时计数；完整输出网格并不能证明底层行情没有缺口。该核验是模拟账户算术贡献，不能称为因果因子归因或真实费用/执行确认。未保存的逐门槛状态、完整目标和外部场所事件仍未知。

最新输出清单 SHA-256：`e58bca7a899b837f8085cfd99ded5c9c5c843409a167043c965852c2fb74828a`。

## 本次发布前实际验证与清理

| 检查 | 本次实际结果 |
|---|---|
| 主机完整 Python 套件 | 1,490 项：1,488 通过、2 失败、0 跳过、0 收集错误；132.865 秒（pytest XML） |
| Ruff lint：src/scripts/tests | PASS |
| Pyright strict | 0 errors、0 warnings |
| 全仓 Ruff format --check | FAIL；1 个既有未修改文件，另 772 个已格式化 |
| 初次沙箱 pytest | Polars CPU 检测在收集阶段报 unknown feature flag: sse3，34 个收集错误；随后主机运行正常收集。未跳过 CPU 检查。 |
| 冻结证据保全 | 10,442 个原版本化工件逐个复核，字节全部不变；10 份新 OUTPUT_MANIFEST 的 299 个条目另行校验通过 |
| 清理 | 32 个未跟踪且未纳入证据清单的缓存目录，153 个文件，共 1,901,740 字节；保留依赖、原始数据、回放和失败记录 |
| 发布文本检查 | 对 2,813 个 UTF-8 文本文件（221,760,726 字节）执行高置信令牌/私钥/带密码 URL 模式检查，0 命中；这不是无秘密的形式化证明 |
| 大文件 | 初始待发布最大文件 23,742,461 字节；完整证据约 1.1 GB，保留其字节身份 |
| 旧本地独立归档 | 本轮退出码 1，因旧裸库仍为 codex-archive 而拒绝；没有迁移分支。与用户明确授权的 GitHub main 推送分别处理。 |
| 完整历史 CI/前端构建 | 本轮未运行；不能以本次 Python 检查代称全部 CI 通过 |

主机测试原始日志内容摘要如下（省略主机名与临时目录，保留原始日志哈希）：


~~~~json
{
  "command": "python -m pytest -q -p no:cacheprovider --basetemp=<task-temp> --junitxml=<task-temp>/pytest.xml",
  "exit_code": 1,
  "suite": {
    "name": "pytest",
    "errors": "0",
    "failures": "2",
    "skipped": "0",
    "tests": "1490",
    "time": "132.865",
    "timestamp": "2026-09-11T09:54:46.358805+08:00"
  },
  "logs": {
    "pytest.xml": {
      "bytes": 227784,
      "sha256": "8d55a59629cd1f53ad967d69befeb44bf205e2213531e8ab3b59d9e8ead3cae7"
    },
    "pytest.stdout.txt": {
      "bytes": 7497,
      "sha256": "6b526f184d6d1d00765dd2d2b7841a35268fd22f0db48a357601e8e3ab8e1963"
    },
    "pytest.stderr.txt": {
      "bytes": 0,
      "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    }
  },
  "failures": [
    {
      "classname": "tests.alpha_v5.test_resize_semantics_contract",
      "name": "test_invoked_pure_functions_match_frozen_sources",
      "message": "AssertionError: assert '5cb1aed0a371...3efab8457031a' == 'c52abbcaf1bb...b5d7e3bc033c1'\n  \n  - c52abbcaf1bbbb90715569a563fc85e57974f89e15ead33cc6db5d7e3bc033c1\n  + 5cb1aed0a371b608fa71007edce183429f6e488ebfa217942b33efab8457031a",
      "traceback": "project_root = WindowsPath('D:/Personal/Quantitative_Trading')\n\n    def test_invoked_pure_functions_match_frozen_sources(project_root: Path) -> None:\n        for name in (\"research/strategies/buffered_target.py\", \"portfolio/optimizer.py\"):\n            relative = f\"src/aegisquant/{name}\"\n            frozen = (\n                project_root / \"artifacts/alpha_v5/20260908_research_churn_v3/implementation\" / relative\n            )\n>           assert sha256_file(project_root / relative) == sha256_file(frozen)\nE           AssertionError: assert '5cb1aed0a371...3efab8457031a' == 'c52abbcaf1bb...b5d7e3bc033c1'\nE             \nE             - c52abbcaf1bbbb90715569a563fc85e57974f89e15ead33cc6db5d7e3bc033c1\nE             + 5cb1aed0a371b608fa71007edce183429f6e488ebfa217942b33efab8457031a\n\ntests\\alpha_v5\\test_resize_semantics_contract.py:37: AssertionError"
    },
    {
      "classname": "tests.architecture.test_risk_boundaries",
      "name": "test_research_and_model_packages_do_not_import_independent_risk_engine",
      "message": "AssertionError: assert ['src/aegisqu...io_replay.py'] == []\n  \n  Left contains 5 more items, first extra item: 'src/aegisquant/research/validation/portfolio_replay.py'\n  Use -v to get more diff",
      "traceback": "project_root = WindowsPath('D:/Personal/Quantitative_Trading')\n\n    def test_research_and_model_packages_do_not_import_independent_risk_engine(\n        project_root: Path,\n    ) -> None:\n        roots = (\n            project_root / \"src/aegisquant/research\",\n            project_root / \"src/aegisquant/intelligence\",\n        )\n        violations: list[str] = []\n        for root in roots:\n            for path in root.rglob(\"*.py\"):\n                tree = ast.parse(path.read_text(encoding=\"utf-8\"), filename=str(path))\n                for node in ast.walk(tree):\n                    if isinstance(node, ast.Import):\n                        names = [item.name for item in node.names]\n                    elif isinstance(node, ast.ImportFrom):\n                        names = [node.module or \"\"]\n                    else:\n                        continue\n                    if any(\n                        name == \"aegisquant.risk\" or name.startswith(\"aegisquant.risk.\")\n                        for name in names\n                    ):\n                        violations.append(path.relative_to(project_root).as_posix())\n>       assert violations == []\nE       AssertionError: assert ['src/aegisqu...io_replay.py'] == []\nE         \nE         Left contains 5 more items, first extra item: 'src/aegisquant/research/validation/portfolio_replay.py'\nE         Use -v to get more diff\n\ntests\\architecture\\test_risk_boundaries.py:34: AssertionError"
    }
  ]
}
~~~~

## 代码路径与审阅边界

当前研究链路可概括为：开发数据路径/哈希守卫 → PIT/可知时间校验 → 趋势与目标仓位 → 平滑/复核/缓冲/舍入成本门槛 → 资金和数量约束 → 下一事件成交与账本 → MTM/共同日历 → 配对统计/准入。新共享资金、执行实证、ML 与最终留出仅在各自合约边界内实现和验证，尚未产生对应的完整真实结果。

核心风险点：①信号/决策/提交/到达/事件/可知时间不可混用；②费用原币与估值币、费用倍率与费用金额不可混用；③季度资金重置与连续账户、共享现金与独立 sleeve 不可混用；④同成交影子成本与重新决策路径不可混用；⑤因果标签必须覆盖未经过滤的成熟机会；⑥跨币重采样应保留同时相关性；⑦研究不得获得绕过独立风控或最终留出的权限。

以下附录采用当前工作树的真实源代码或冻结报告原文。未包含全仓所有模块、原始行情、全部 430 个原始结果/trace 文件及全部尾部大表；需要更多实现时按路径索取，不应根据片段臆测未提供代码。函数片段从 AST 起止行提取，行号指原文件；整文件片段明确标注。附录中的旧状态属于该来源产生时点。

## 附录 A：关键配置与机器可读证据

### configs/research/aegis_alpha_v5.yaml

来源：[configs/research/aegis_alpha_v5.yaml](https://github.com/tORHANSxd/AegisQuant/blob/main/configs/research/aegis_alpha_v5.yaml)；SHA-256：`c4b7a2e734168ea31385ccf0416963e2dc532cb416293710f6dd6891a8deca5c`。


~~~~yaml
generation: alpha-r5-research-churn-20260908-v3
predecessor: artifacts/alpha_v5/20260908_research_churn_v2
generation_change: STRICT_DECIMAL_JSON_RESTORE_FIX_BEFORE_NEW_STRATEGY_REPLAY_NO_PARAMETER_CHANGE
taskbook: deep-research-report.md
scope: FIRST_BATCH_RESEARCH_VALIDITY_AND_CHURN_ONLY
evidence_tier: RETROSPECTIVE_DEVELOPMENT
development:
  start: '2021-01-01T00:00:00Z'
  test_start: '2022-04-01T00:00:00Z'
  end_exclusive: '2025-10-01T00:00:00Z'
  classification: PREVIOUSLY_USED_DEVELOPMENT_DATA
  source_manifest: artifacts/alpha_v4_multi_asset/source_manifest.json
  partition: HASHED_DEVELOPMENT_ONLY_CSV_SELECTED_BEFORE_OHLCV_PARSING
universe:
  mode: LEGACY_FIXED_SURVIVOR_DIAGNOSTIC_ONLY
  promotion_evidence_eligible: false
  point_in_time_membership_manifest: null
  minimum_history_4h_bars: 240
  minimum_trailing_30d_quote_volume: null
  include_delisted_required: true
final_holdout:
  status: NOT_ALLOCATED_INSUFFICIENT_EVIDENCE
  start: null
  end_exclusive: null
  path: null
  sha256: null
  minimum_months: 12
  development_access_allowed: false
protected_data_roots: [artifacts/alpha_v4/holdout, artifacts/alpha_v5/holdout]
new_return_model_fits: 0
new_calibration_fits: 0
parameter_selection_from_results: false
initial_cash_per_symbol: '10000'
primary_candidate: G1
buffer:
  relative_half_width: '0.10'
  restore_half_width: '0.20'
  reduce_half_width: '0.10'
  absolute_weight_floor: '0.03'
resize:
  smoothing_half_life_days: 5
  review_interval_hours: 48
  minimum_weight_change: '0.03'
  minimum_notional: '50'
  cost_benefit_lambda: '1'
risk_benefit:
  definition: 'max(0, ((w_current-w_raw)^2-(w_proposed-w_raw)^2) * annual_vol^2 * review_years / 2)'
  units: EQUITY_NORMALIZED_VARIANCE_TRACKING_UTILITY_PROXY
  comparison: ACTUAL_ROUNDED_INCREMENT_COST_DIVIDED_BY_EQUITY
  interpretation: NOT_EXPECTED_ALPHA_OR_VERIFIED_EXECUTION
  hard_exits_and_caps_bypass: true
review_clock: ELAPSED_SINCE_LAST_REVIEW_OR_SUBMITTED_ORDER
arms:
  G0: {kind: FROZEN_R4_F3, costs: ['1']}
  G1: {kind: RESIZE_V2, costs: ['1', '1.5', '2']}
  G1_H3: {kind: RESIZE_V2, smoothing_half_life_days: 3, costs: ['1']}
  G1_H10: {kind: RESIZE_V2, smoothing_half_life_days: 10, costs: ['1']}
  G1_R24: {kind: RESIZE_V2, review_interval_hours: 24, costs: ['1']}
  G1_R72: {kind: RESIZE_V2, review_interval_hours: 72, costs: ['1']}
  G1_PASSIVE: {kind: SAME_RISK_PASSIVE, costs: ['1', '1.5', '2']}
neighbor_rule: FIXED_ONE_FACTOR_DIAGNOSTICS_NO_WINNER_SELECTION
benchmark_evidence:
  frozen: [CASH, F0, F3, F5]
  matched_risk: [G1_PASSIVE]
  risk_scope: INDEPENDENT_EQUAL_INITIAL_CASH_SLEEVES_NOT_PORTFOLIO_COVARIANCE_TARGET
execution_evidence: CLOSED_BAR_PROXY_NOT_VERIFIED_FEE_RULE_ORDERBOOK_LATENCY
churn_acceptance:
  maximum_resize_fill_share: 0.50
  maximum_turnover_relative_to_f0: 0.60
  maximum_cost_relative_to_f0: 0.70
  maximum_cagr_degradation_pp: 1.0
  maximum_mdd_degradation_pp: 2.0
statistics:
  seed: 20260908
  repetitions: 10000
  correction: HOLM
  comparisons: [G1-G0, G1-F0, G1-F5, G1-G1_PASSIVE, G1-CASH, G1_H3-G0, G1_H10-G0, G1_R24-G0, G1_R72-G0]
production_policy: CASH
selected_model_id: null
production_ml_enabled: false
paper_trading_admitted: false
live_trading: false
order_submission_enabled: false
~~~~

### configs/research/alpha_v5_pit_contract.yaml

来源：[configs/research/alpha_v5_pit_contract.yaml](https://github.com/tORHANSxd/AegisQuant/blob/main/configs/research/alpha_v5_pit_contract.yaml)；SHA-256：`65743cec992c15582b4cc5072f01a8292fbab03953e94f346026617226edd58a`。


~~~~yaml
schema_version: aegis-pit-contract-b2-v1
generation: alpha-r5-pit-contract-20260910-v1
output: artifacts/alpha_v5/20260910_pit_contract_v1
scope: B2_PIT_CONTRACTS_AND_SYNTHETIC_TESTS
mode: PIT_DATA_QUALITY_ONLY
branch_required: main
source_head: d8c6d4013097f6323ab8b7a424c860ba0ccbd62b
taskbook: AegisQuant_整改与验证方案_20260909.md
r5_frozen_root: artifacts/alpha_v5/20260908_research_churn_v3
r5_manifest_sha256: a57b381069473e4f86c3c161452fb4da6840d0401171d3f1fa7f5af160f946ce
b0_frozen_root: artifacts/alpha_v5/20260909_review_contract_v2
b0_manifest_sha256: fccc6e6a60185811d37b4e8a40a7772da3209b46e95ea15e83cfef9d39519edf
budgets:
  data_quality_jobs: 1
  historical_strategy_engine_runs: 0
  real_return_model_fits: 0
  real_calibration_fits: 0
  final_holdout_accesses: 0
  real_orders: 0
input_root: data/research/pit
inputs:
  universe_events: {path: null, sha256: null}
  liquidity_windows: {path: null, sha256: null}
  rules_provenance: {path: null, sha256: null}
  coverage_manifest: {path: null, sha256: null}
period_start: '2022-04-01T00:00:00+00:00'
period_end_exclusive: '2025-10-01T00:00:00+00:00'
strict_data_quality: true
allow_synthetic_historical_evidence: false
minimum_history_4h_bars: 240
minimum_trailing_30d_quote_volume: null
maximum_liquidity_age_hours: 4
warmup_requirements:
  trend_40d: 241
  trend_80d: 481
  trend_160d: 961
  volatility_42_returns: 43
warmup_basis: src/aegisquant/research/strategies/cost_aware_trend.py::build_trend_features
legacy_symbols: [BNBUSDT, BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT]
research_conclusion: NO_PROVEN_ALPHA
production_policy: CASH
production_ml_enabled: false
paper_trading_admitted: false
live_trading: false
order_submission_enabled: false
~~~~

### configs/research/alpha_v5_portfolio_contract.yaml

来源：[configs/research/alpha_v5_portfolio_contract.yaml](https://github.com/tORHANSxd/AegisQuant/blob/main/configs/research/alpha_v5_portfolio_contract.yaml)；SHA-256：`d300ffa145459a86a9792541ba5f006184de2a8929f068e403e1729456bed643`。


~~~~yaml
schema_version: aegis-portfolio-contract-b5-v1
generation: alpha-r5-portfolio-contract-20260910-v1
output: artifacts/alpha_v5/20260910_portfolio_contract_v1
scope: B5_PORTFOLIO_BRIDGE_AND_SYNTHETIC_CONTRACT_TESTS
branch_required: main
source_head: d8c6d4013097f6323ab8b7a424c860ba0ccbd62b
budgets:
  contract_jobs: 1
  historical_strategy_engine_runs: 0
  real_return_model_fits: 0
  real_calibration_fits: 0
  final_holdout_accesses: 0
  real_orders: 0
sources:
  r5_manifest:
    path: artifacts/alpha_v5/20260908_research_churn_v3/audit_manifest.json
    sha256: a57b381069473e4f86c3c161452fb4da6840d0401171d3f1fa7f5af160f946ce
  b4_manifest:
    path: artifacts/alpha_v5/20260910_execution_contract_v1/OUTPUT_MANIFEST.json
    sha256: bc4687a0c6e5c9ae76d1021a69d769d22fb7699ef566c8cf495c10afa02023d3
  b2_safety:
    path: artifacts/alpha_v5/20260910_pit_contract_v1/safety_and_budget_audit.json
    sha256: c9f727179b729265cb22d70d445ac0ac44ae1d7f5802a6ba5bec03065e1a4d26
historical_portfolio_inputs: null
economic_policy_adopted: false
proposed_risk_policy:
  return_frequency: UTC_DAILY
  lookback_calendar_days: 90
  ewma_half_life_days: 30
  diagonal_shrinkage: '0.20'
  covariance_basis: TOTAL
  annualization_days: '365.25'
  volatility_target_annual: '0.12'
  gross_max: '1.0'
  single_asset_max: '0.30'
  crypto_cluster_gross_max: '0.40'
  cvar_confidence: '0.95'
  cvar_loss_daily_max: '0.02'
  drawdown_window_days: 30
  drawdown_soft: '0.08'
  drawdown_hard: '0.12'
  automatic_recovery_allowed: false
  enable_for_live: false
future_scenarios:
  modes: [INDEPENDENT_SLEEVES, SHARED_CASH_BRIDGE, SHARED_CASH_WITH_RISK]
  stress_paths: [JOINT_CORRELATED_GAP, DEPTH_LATENCY_AND_VENUE_HALT, USDT_DEPEG_AND_BLOCKED_EXIT]
  capital: '50000'
  authorized_runs_now: 0
research_conclusion: NO_PROVEN_ALPHA
production_policy: CASH
production_ml_enabled: false
paper_trading_admitted: false
live_trading: false
order_submission_enabled: false
~~~~

### configs/research/alpha_v5_saved_run_audit.yaml

来源：[configs/research/alpha_v5_saved_run_audit.yaml](https://github.com/tORHANSxd/AegisQuant/blob/main/configs/research/alpha_v5_saved_run_audit.yaml)；SHA-256：`3c7d3faad9bce7b2a309621443b82fe1c9e7ef3fb446c1dd8aa2caa49a6a62d3`。


~~~~yaml
schema_version: aegis-saved-evidence-audit-v1
generation: alpha-r5-saved-evidence-20260910-v2
output: artifacts/alpha_v5/20260910_saved_evidence_v2
scope: B1_SAVED_SIMULATION_JOINS_NO_REPLAY
branch_required: main
source_head: d8c6d4013097f6323ab8b7a424c860ba0ccbd62b
budgets:
  contract_jobs: 1
  historical_strategy_engine_runs: 0
  real_return_model_fits: 0
  real_calibration_fits: 0
  final_holdout_accesses: 0
  real_orders: 0
sources:
  r5_manifest:
    path: artifacts/alpha_v5/20260908_research_churn_v3/audit_manifest.json
    sha256: a57b381069473e4f86c3c161452fb4da6840d0401171d3f1fa7f5af160f946ce
  b0_catalog:
    path: artifacts/alpha_v5/20260909_review_contract_v2/evidence_contract.json
    sha256: 696be552a769b21f63cf0bf488feacd767d90958682126fae0b6fdf104fb9724
  b0_baseline:
    path: artifacts/alpha_v5/20260909_review_contract_v2/preflight/baseline_workspace.json
    sha256: d0a38317bd5114b2c12375653b268c29ad9e553787fcb9b94d6c3cfd3fefcf7f
  b7_manifest:
    path: artifacts/alpha_v5/20260910_final_contract_v1/OUTPUT_MANIFEST.json
    sha256: b96416c3931b9b2870afae05092770e1f4ea66ca798ec56c1c5c7f783cabc094
  r4_registry:
    path: artifacts/alpha_r4/20260908_v1/experiment_registry.json
    sha256: ab77f669e9dabedd303d2706b506f09c9c63904b40a03d9f92e7363046b4aebf
  prior_saved_manifest:
    path: artifacts/alpha_v5/20260910_saved_evidence_v1/OUTPUT_MANIFEST.json
    sha256: 188cdaa378d9a28916f279453fce7faad61850428cf9d470731e7904f8a5808c
saved_scope:
  r5_registered_runs: 55
  r4_registered_segments: 160
  new_strategy_runs: 0
r4_cost_1_arms: [F0, F1, F2, F3, F4, F5]
source_period: ['2022-04-01T00:00:00Z', '2025-10-01T00:00:00Z']
tail_fraction: '0.05'
research_conclusion: NO_PROVEN_ALPHA
production_policy: CASH
production_ml_enabled: false
paper_trading_admitted: false
live_trading: false
order_submission_enabled: false
~~~~

### artifacts/alpha_v5/20260910_saved_evidence_v2/evidence_gaps.json

来源：[artifacts/alpha_v5/20260910_saved_evidence_v2/evidence_gaps.json](https://github.com/tORHANSxd/AegisQuant/blob/main/artifacts/alpha_v5/20260910_saved_evidence_v2/evidence_gaps.json)；SHA-256：`fd5b64636f4a24ec48476b38ac9862a9ce5a0d791798153a03f7ba381085db0f`。


~~~~json
{
  "still_unverified": [
    "EVERY_INTERNAL_GATE_AND_PRE_VETO_POST_SECOND_ROUNDING_TARGET",
    "EXTERNAL_ACK_CANCEL_AND_QUEUE_EVENT_STREAM",
    "INDEPENDENT_PIT_FEE_RULE_DEPTH_LATENCY",
    "CAUSAL_FACTOR_AND_EXECUTION_DECOMPOSITION_OF_TAIL",
    "COMPLETE_TRIAL_HISTORY_AND_UNUSED_HOLDOUT"
  ],
  "old_reports_preserved": true,
  "real_execution_verified": false,
  "research_conclusion": "NO_PROVEN_ALPHA"
}
~~~~

### artifacts/alpha_v5/20260910_saved_evidence_v2/prior_output_issues.json

来源：[artifacts/alpha_v5/20260910_saved_evidence_v2/prior_output_issues.json](https://github.com/tORHANSxd/AegisQuant/blob/main/artifacts/alpha_v5/20260910_saved_evidence_v2/prior_output_issues.json)；SHA-256：`ed249b73e481cb7041c84ac1eefb60a12fe4e67a9d68d79eb3b134d70555be17`。


~~~~json
{
  "source_manifest": "artifacts/alpha_v5/20260910_saved_evidence_v1/OUTPUT_MANIFEST.json",
  "status": "V1_COST_GROUP_LABELS_SUPERSEDED_BY_V2",
  "defect": "V1_ROW_COST_AMOUNT_OVERWROTE_COST_SCENARIO_TAG",
  "affected": [
    "run_summary_cost_tag",
    "fill_join_cost_tag",
    "ordinary_fill_count_groups"
  ],
  "unaffected": [
    "original_source_bytes",
    "per_run_ledger_mtm_checks",
    "twelve_tail_groups"
  ],
  "repair": "COST_SCENARIO_IN_COST_AND_MONEY_IN_PAID_COST_WITH_COLLISION_REJECTION",
  "prior_output_preserved": true,
  "new_strategy_or_significance_calculations": false
}
~~~~

### artifacts/alpha_v5/20260910_saved_evidence_v2/safety_and_budget_audit.json

来源：[artifacts/alpha_v5/20260910_saved_evidence_v2/safety_and_budget_audit.json](https://github.com/tORHANSxd/AegisQuant/blob/main/artifacts/alpha_v5/20260910_saved_evidence_v2/safety_and_budget_audit.json)；SHA-256：`4a392ed6ff086b9e47fe3fdc4f9fc1cc443957116235b54f2cae6c517bce002f`。


~~~~json
{
  "actual": {
    "contract_jobs": 1,
    "historical_strategy_engine_runs": 0,
    "real_return_model_fits": 0,
    "real_calibration_fits": 0,
    "final_holdout_accesses": 0,
    "real_orders": 0
  },
  "authorized": {
    "contract_jobs": 1,
    "historical_strategy_engine_runs": 0,
    "real_return_model_fits": 0,
    "real_calibration_fits": 0,
    "final_holdout_accesses": 0,
    "real_orders": 0
  },
  "before": {
    "status": "VERIFIED",
    "files_checked": 12342,
    "changed": [],
    "protected_holdout_contents_read": false,
    "basis": "SHA256 before implementation and after audit"
  },
  "after": {
    "status": "VERIFIED",
    "files_checked": 12342,
    "changed": [],
    "protected_holdout_contents_read": false,
    "basis": "SHA256 before implementation and after audit"
  },
  "live_lock_literals": {
    "LIVE_TRADING": false,
    "ORDER_SUBMISSION_ENABLED": false,
    "LIVE_ADAPTERS": []
  },
  "production_policy": "CASH",
  "research_conclusion": "NO_PROVEN_ALPHA",
  "production_ml_enabled": false,
  "paper_trading_admitted": false,
  "live_trading": false,
  "order_submission_enabled": false,
  "alpha_trials": 0,
  "promotion_admitted": false
}
~~~~

## 附录 B：最新阶段报告原文

### artifacts/alpha_v5/20260909_review_contract_v2/report.md

SHA-256：`3393d30b9fff2c5d17aed4480d99c621b1f44b82812f5fc241e2aa42f96fc9d6`。


~~~~markdown
# R5 B0 与 B1 只读／合成证据契约审计

**NO_PROVEN_ALPHA / CASH。ML、纸面准入、实盘及订单提交全部关闭。**

本批 generation：`alpha-r5-review-contract-20260909-v2`。实际读取已提交基线 `d8c6d4013097f6323ab8b7a424c860ba0ccbd62b` ＋本地冻结 R5 v3 源码与保存表；近期证据始终是 R4 F3。
历史策略回放 0、真实模型拟合 0、真实校准拟合 0、最终留出访问 0、真实订单 0；没有重算显著性。
报告累计尝试 2 次，每个独占 generation 使用 1 个报告槽；此前失败均保留并纳入 failure_history_index.json。
原始市场逐行审计、逐单资金账本重建和完整 trace→order→fill 联结未完成（NOT_VERIFIED）。

## 实际证据范围

20260909 精简包、版本图、包补丁、MANIFEST、原 readable CSV 及完整 ZIP 未收到（NOT_RECEIVED）。随附算术审计 JSON 是历史审阅记录，本批未冒称完成其中的 2,465 文件包验证。
使用本地冻结 Parquet 和 JSON 完成 Decimal 算术核对；新 readable CSV 仅是本批派生导出。原 result.json.gz 与 trace 文件存在，已核对哈希／schema，但未解压重建原始逐单凭证。完整新 trace 字段也未保存。
G1 近期试验没有执行，状态为 NOT_COLLECTED；近期 F3 没有改名、拼接或变为 G1 样本外。

## 算术、成本与统计

- 17 个 arm/cost 组合共同 UTC 日历与四小时日历、50,000 USDT 初始资金、cash + inventory = equity、终值和 14 季度复合核对通过；空仓日及付费终止边界保留。
- R5 派生成交 3181 行，R4 13504 行；所有组合的成交数、普通调仓理由数、名义金额及成本对齐保存汇总。G1 为 176 fills、12 次普通 resize，restore=0；F0 为 1814/2022。
- G1−F0 终值差 `16060.45311570832` USDT；账面成本节省 `1693.0537393882996`；各自路径终值加回成本之差 `14367.3993763200204`。最后一项不是零成本资金回放或 alpha。
- 三种成本模式分别命名；funded 模式不要求费用越高终值越低。35 个 same-fill 影子分组的嵌套成本和净值恒等式通过，实际 fill-path 身份及资金可实现性仍未验证。
- 原 9 个比较及其 raw/adjusted p、CI、bootstrap 元数据完整保留。p 值对应日均收益差；CI 对应未作多重校正的复合收益差。未重采样；DSR/PBO 与独立 trial 数均为 null。
- G1 原五项 churn 门槛通过与 NO_PROVEN_ALPHA 同时保留；盈利季度 6/14、Holm 未通过仍是旧研究结论。
- 容差提前固定：保存 Float64 表的资金 1e-8 USDT、收益 1e-10；原字符串成本分项 1e-18 USDT。残差逐组输出，无静默取整。无原始现金流账本不能凭余额恒等式排除历史额外入金。

## G1 合成机制

方差效用 `0.000008969199178644763860369609855` NAV；合成 16bps 的单腿成本 `.000112` NAV，成本／效用 `12.48717948717948717948717949`。增大乘在收益侧的 lambda 放宽门槛；移动远离 raw 的效用截为 0。16bps 没有被标作历史实测费用。
时钟表遵循冻结语义：到期且具备持仓／行情／趋势、无 pending 的复核先更新 review；成本否决也消耗该次复核。SUBMIT 更新 review，REJECT／FILL／CANCEL 本身不更新。pending 不凭空删除，硬退出仍受订单协调与真实可成交条件约束。
raw/smoothed/proposed 冲突、全部门槛漏斗、二次取整、gap 后所有指标 warmup、硬退出与尾部共同冲击列为待验证；不补造拒绝数或最差事件日期。

## 验证与保全

本批实际命令及全部结果见 `validation/test_commands_and_results.txt`，共记录 26 次检查调用；不是旧 1,188 项日志。仅执行新增纯测试及针对新文件的静态检查，未运行全仓 pytest。
实施前后 10478 个已有文件 SHA256 保持不变。用户 tracked/untracked 改动保留；没有 reset、clean、分支创建、提交或推送。新增文件与 diff 见 `changed_files.json` / `changes_this_batch.patch`。
现有失败代次、失败配置及 H3/H10/R24/R72 全部保留。错误会消费独占 generation 并保存日志；输出 manifest 以 exclusive create 封存，重用目录被拒绝。
本批 v1 因新审计器把派生 filled_qty 误当非负量而失败。冻结源码约定 BUY 为正、SELL 为负，名义额为正；v2 只修审计契约并增加买卖方向／零量反例，历史策略及源表不变。v1 是审计工程失败，不是新的 alpha 试验。

## 缺口与停止

包级版本／manifest 缺件见 evidence_gaps；现有原始文件只做 hash/schema 核对，完整原始账本联结和新字段仍未验证。真实历史费用、规则、盘口、延迟、PIT、全量独立试验史和未使用留出仍缺证据。
最小后续是另批提供精简包／完整包，核对包身份后只读联结现有原始凭证；若需要产生新的 trace 字段或历史机制消融，必须另获授权并使用新 generation。本批不进入该工作。
**本批完成即停止。最终仍为 NO_PROVEN_ALPHA / CASH，所有准入与订单开关关闭。**
~~~~

### artifacts/alpha_v5/20260910_pit_contract_v1/report.md

SHA-256：`550897fb1640a3d2a10a9752faf6e2b3a243a1a3287e86e9e729d23633f635a6`。


~~~~markdown
# B2 PIT 数据契约与合成验证

**NO_PROVEN_ALPHA / CASH；ML、纸面准入、实盘和订单提交全部关闭。**

Generation：`alpha-r5-pit-contract-20260910-v1`；身份：已有 main `d8c6d4013097f6323ab8b7a424c860ba0ccbd62b` + 冻结 R5 v3 + B0/B1 v2。
历史策略回放、真实模型拟合、真实校准拟合、最终留出访问、真实订单全部为 0。

工程验证：49 项限定纯测试通过；Ruff、格式和类型检查通过。实际 10 次检查记录及失败尝试均保留。
严格数据质量状态：`FAILED_CLOSED_INSUFFICIENT_PIT_EVIDENCE`；独占数据质量作业 1 次，不因缺件重开。

新增事件级修订与同键冲突检查，区分公告、接收、修订和生效时间；重上市使用独立 instrument UID。
连续历史按已登记依赖取最大值：40/80/160 日趋势分别需 241/481/961 根闭合四小时数据，42 个收益的波动窗口需 43 根。
30 日 quote turnover 直接对带哈希明细求和；零量、缺口、proxy、短历史及未知规则不能打开新风险。
新严格模式按交易状态变化重新证明连续 warm-up；不修改冻结 G1 的 gap、参数、费用或下单行为。
仅返回新开风险资格，已有持仓身份原样保留；不删除、免费平仓或借用未来退市价格。

future-mutation 只覆盖本批 PIT 的事件、流动性、规则和跨币资格快照；合成测试不代表真实行情、特征、风险、订单或成交前缀已经重验。
旧 legacy 五币研究函数体保持冻结语义；旧回放测试未运行。新入口 pit-audit 只进入数据质量作业。

实际数据表、来源和 schema 见 universe_events/liquidity_windows/rules_provenance/coverage_manifest；未收到用 records=null 表达，不把缺件变成空市场。
缺全历史候选/退市证据或未登记流动性阈值时，历史覆盖率、独立全市场核验与成分差异保持未知；不把今天的币表或 base_volume×close 回填成真实 PIT。
保护范围内 12069 个既有文件哈希未变；本批五个允许修改文件的原字节、八个实施文件与补丁均保存。

下一步所需输入仅列于 evidence_gaps.json；取得真实来源及新 generation 后才能重新开展严格数据质量核验。本批不进入 B3 或任何收益/交易实验。
~~~~

### artifacts/alpha_v5/20260910_benchmark_contract_v1/report.md

SHA-256：`2c4efbbe83a9f780592f68722bdb590bea9c8eb4136a297feb7020511ce91f18`。


~~~~markdown
# B3 共同风险基准：契约与合成验证

**NO_PROVEN_ALPHA / CASH；ML、纸面准入、实盘及订单提交全部关闭。**

Generation：alpha-r5-benchmark-contract-20260910-v1；已有 main d8c6d4013097f6323ab8b7a424c860ba0ccbd62b，绑定冻结 R5 v3、B0/B1 v2 和 B2 v1。
本批 44 项限定纯测试、Ruff、格式和类型检查通过；19 条实际检查记录（含失败尝试）全部保存。
已完成六风险臂＋CASH契约、只读入口、完整现金日历、2×3描述性归因和配对对数净收益统计接口。
历史策略回放、真实模型拟合、真实校准拟合、最终留出访问、真实订单及历史统计重采样均为 0。

两个信号固定为始终持有、现有10/40趋势；三类控制为G0/F3、原G1、入场后数量固定且保留硬退出/硬上限。
G0/G1控制复用现有构造函数；数量固定臂本批仅定义契约，执行适配与真实引擎等价尚未完成。
相同事前限制不保证实现波动相同；禁止以全样本实现波动反推交易权重。账户仍为五个10,000 USDT独立sleeve，无跨币资金转移。
同配置路径测试只验证提供的经济记录比较器，不冒充实际引擎会产生相同订单。

新的四项主要比较：G1 对 CASH、F5_MATCHED、G1_PASSIVE、SIMPLE_TREND。区间和单侧p值使用同一平均对数净收益差estimand，UTC日采样、同时间块联合抽样、四项一起Holm。
新矩阵、归因、四项统计及影子成本均 NOT_COLLECTED；旧F0–F5及旧G1曲线不改名填入。旧九项比较原字节及不同CI/p estimand身份保留，不重算历史显著性。
现金参考保留 7675 个四小时点和付费退出边界；它是确定性参考，不证明六个风险臂已具备同一日历。

B2仍缺真实PIT资料；真实因子、事前风险及完整执行证据也不足，全部缺口见 evidence_gaps.json。合成通过不能取得研究或交易晋级。
方案90次历史矩阵仅记录为未来规模，当前授权槽位0；本批只消费1次契约报告作业。
保护范围内 12110 个既有文件未变；两处修改的原字节、七个实施文件和本批补丁已封存。
本 generation 仅封存 B3 契约；后续工程按各自范围和证据门槛继续，历史矩阵、真实拟合及最终留出保持关闭。
~~~~

### artifacts/alpha_v5/20260910_execution_contract_v1/report.md

SHA-256：`6dee0a24993abaef718c2f026b1e47121390c436e257f058deb1aff79db2fd49`。


~~~~markdown
# B4 有效时点执行与成本契约

**NO_PROVEN_ALPHA / CASH；ML、纸面准入、实盘、订单全部关闭。**

已实现显式成交参考价、已包含成本组件、费用可知时间与有效时间分离、逐部分成交的费用币种/优惠/余额回退、共同 impact 正反函数及时间窗口绑定。旧执行线性代理、旧容量平方根代理分别保留；显式新版输入才采用统一模型。

共享流动性工具复用 decide_fills，检查订单到达/撤单时序、maker queue 未知、窗口总绝对成交额和每事件深度消耗。它只处理输入的同一币种/场所、已知累计窗口截止事件；当前返回 SYNTHETIC_ONLY，不把窗口成交量宣称为瞬时盘口。未成交量和 FOK 失败保留。

SPOT_NATIVE_FEES_V2 为显式独立账本规则：基础币手续费按成交价作 FIFO 库存处置，返佣建立带成本基础的新 lot；交易与费用余额不足时在修改前拒绝。第三币若另有该币交易 lots，必须取得对应估值并接入处置协议，目前明确拒绝。旧账本默认及冻结回放参数保留。

合成 fixture、既有相关纯测试和静态检查见 validation/；真实样本缺失，不能以这些通过记录宣称执行模型已校准。独立校准/验证分割、残差分桶和容量曲线均未采集，实际数据切分与模型拟合为零。真实费用、FX、L1/L2、逐笔和延迟等缺口见 evidence_gaps.json。

仅消费一次本 generation 协议报告；历史策略回放、真实收益模型/校准拟合、最终留出访问和真实订单均为零。后续 B5-B7 工程继续按证据门槛推进。
~~~~

### artifacts/alpha_v5/20260910_portfolio_contract_v1/report.md

SHA-256：`dc002b1af8987ee2d861a7051b1793997c9eb3712eb8d4475d544fc30830b63a`。


~~~~markdown
# B5 组合风险与共享资金契约

**NO_PROVEN_ALPHA / CASH；ML、纸面准入、实盘、订单全部关闭。**

已为 covariance 增加 TOTAL/RESIDUAL、单位和 PSD 契约；只有浮点容差内的小负特征值允许固定修正并记录。90 个完整 UTC 日的 EWMA/shrinkage 使用固定规则，缺币或缺日失败。原数值调用保留；显式目标投影直接使用已有 raw targets，期望收益字段为 0，不把二元趋势信号当收益预测。

共享资金适配器读取原 ledger，计入真实可用现金、pending BUY 预留、未结算收入与未完成卖出。按固定比例预算并向下取整，逐次检查最坏成交顺序和取整后的风险。partial fill 后要求重新读取账本及风险快照。硬风险减仓可越过普通换手限额，但流动性不够、撤单未确认或场所停摆时保留持仓与 BREACH。

显式 SPOT_NATIVE_MTM_V2 估值避免在已经按现价估值的现货余额上再次叠加 lot 浮盈。旧估值默认不改。费用币资产仍必须有可知 FX，底层原生币账本继续复用；没有另造账本或下单器。

风险贡献、30 日回撤与全期回撤分开。90 日 CVaR95 的尾部点不足以证明安全，状态保持 UNKNOWN，必须补充独立时间块不确定性和联合压力。任务书的风险数值仍是待经济采用的研究起点，本批不启用该风险配置做真实研究。

仅完成接口及合成验证。三模式九个历史组合回放、真实预测/实现风险、资金共享贡献、尾部非劣与容量均 NOT_COLLECTED；不能由工程通过推断风险策略或 alpha 准入。历史回放、真实模型/校准拟合、最终留出读取、订单均为 0。
~~~~

### artifacts/alpha_v5/20260910_ml_contract_v1/report.md

SHA-256：`e83ba0a8d9ef123da8f7d2aa032fb4dd1552d024d29cf834d7091f648d0ca47c`。


~~~~markdown
# B6 ML、episode 与统计契约

**NO_PROVEN_ALPHA / CASH；ML、纸面、实盘和订单继续关闭。**

新增完整基础机会集的 episode 包装，复用可执行 t+1、双腿成本与路径标签；被拒绝机会保留 COUNTERFACTUAL 标记。严格分割按完整特征依赖、标签可用时间、同时间资产组和 episode 清除所有后续边界重叠，记录 purge 和不成熟尾部。旧调用和默认输出契约保留。

三个 outer 块固定为 2022-04 至 2023-06、2023-06 至 2024-08、2024-08 至 2025-10，共 42 个月，最后九个月各三块 inner 验证。仍是已使用开发区间；缺真实标签时只输出日期协议，不能宣称有三个有效统计 fold。

OOF 元数据绑定每个训练、转换和预测的样本、episode、时钟及哈希。校准入口使用对齐的 OOF 预测；模型不可用不能否决风险减仓。预测分布与均值估计不确定性分别记录；conformal 不保证非平稳市场精确覆盖，30 行代码门槛不代表有效样本充分。

未来拟议 144 模型 fit、6 校准 fit 全部列出；当前实际均为 0。内层额外校准和 OOF 均值重拟合没有预算，保持关闭。合成 callback 仅检查原 registry 的失败消耗，不是实际模型拟合。真实训练入口仍未启用。

DSR 缺全试验史、频率/峰度/依赖依据时返回 INSUFFICIENT 和 null；PBO 使用相同登记 score、全部候选和 mid-rank/tie 权重，不因数组顺序造优胜。旧统计实现只保留历史复现兼容，不给新准入证据使用。

episode 实证、outer 指标、OOF 覆盖、经济增量与候选冻结全部 NOT_COLLECTED；实际历史回放、真实模型/校准 fit、最终留出和订单均为 0。本批工程通过不代表 ML 有效或可交易。
~~~~

### artifacts/alpha_v5/20260910_final_contract_v1/report.md

SHA-256：`e753e955ab24e24685471c5f857e264a6eb435e56353d6bdc2a270194cec4bba`。


~~~~markdown
# B7 一次性留出契约与整改工程交付

**NO_PROVEN_ALPHA / CASH；ML、纸面准入、实盘、订单全部关闭。**

本批为最后的工程契约：全项目使用同一个固定位置的 claim 和共享访问日志，候选、路径和 generation 不产生新次数。已有入口在读取前核验项目锚点、明确授权、完整冻结、数据身份和未使用十二个月条件；无锚点、无扩展冻结、未知来源或已用源尾部都拒绝。claim 以 exclusive create 和 fsync 落盘后才允许读取，loader 异常、内容 hash/长度不符仍消耗 claim；缺失或损坏已有日志不能自动初始化新次数。

读取范围守卫覆盖声明的原始、别名及派生数据；开发加载器按登记的 hash/完整血缘拒绝缓存、预览和特征间接引用。应用级守卫不能替代操作系统权限或独立不可回滚存储；真实准入仍要求独立存储证明。当前没有创建真实锚点，也没有读取、预览或 hash 真实最终留出内容，所有访问测试仅使用临时合成文件。

原冻结 manifest 增加版本化的风险、规则、容量、统计、比较族、试验史、模型权重、定期更新程序和独立预审绑定。即使未来所有门槛通过，也只交独立准入评审，不自动改模型别名或打开订单。失败、不确定、读取异常都不能回到同一留出改特征再试。

B0/B1 至 B7 的当前授权工程与必要合成验证已依次交付，各批原始失败记录和封存证据保留，详见 all_batches_status.json 与各自 manifest。每批测试数量有重叠，不能相加当作独立测试总数。本批精确检查数量见 source_and_version_bindings.json。

完整研究验收尚未完成：真实 PIT、费用/规则/盘口/延迟、共享现金历史回放、成熟机会及全试验史、真实 OOF/outer 和未使用留出仍缺证据或后批授权。现有已用历史不能改名为最终留出。当前历史策略回放、真实收益模型拟合、真实校准拟合、最终留出读取和实盘订单五项累计新增均为 0。
~~~~

### artifacts/alpha_v5/20260910_saved_evidence_v2/report.md

SHA-256：`2a33ba827d7317cf30c3d02aa2c3f740d28b105ddb1d0f979bbc720dba5ff0fc`。其中测试数量与历史归档错误只代表该冻结时点；本次全仓验证见正文。


~~~~markdown
# 全部 17 组已保存原始模拟记录只读核验

**NO_PROVEN_ALPHA / CASH；模型、纸面、实盘和订单继续关闭。**

本批核验原 R5 的全部 55 个保存结果及原 R4 的 F0–F5 共 160 个保存分区（F0/F1 各 70 个季度，F2–F5 各 5 个连续 sleeve），覆盖原汇总的全部 17 个策略/成本组；所有输入先与 B0 封存哈希核对。当前结果：**VERIFIED_STORED_SIMULATION**。这是读取原始模拟记录后的联结与算术核验，没有调用策略引擎、重建行情、重定价成交、训练或重新计算显著性。此前 HASH_ONLY/NOT_VERIFIED 报告保留，不能把本报告倒填成此前已经完成。

v1 的逐 run 对账和 12 组尾部核验已完成，但新汇总将成本金额与成本倍率同名为 cost，覆盖了 run/fill 的倍率标签，普通调仓表因此按金额错误分组。v1 原目录及 manifest 保留，问题详情见 prior_output_issues.json。本 v2 以 cost 记录冻结倍率、paid_cost 记录费用金额，并拒绝标签冲突；重新读取原保存数据核对元数据后才输出替代表，同时补齐 F1–F5。它没有重新运行任何原策略。

逐单核对 trace→order→fill→ledger、数量/时钟/费用资产、原账本哈希链和每资产借贷平衡，并从已有 postings 和 lot changes 核对每个已保存 MTM 的资金、原生库存和已记录价格。F0/F1 季度边界要求付费退出与下一季度初始资金一致，不能遗漏不利边界。检查逐项计数和失败示例见 raw_order_fill_ledger_audit.json；失败不会被删掉或强制改成预期数字。原 G1/1 的普通减仓为 12 笔、普通恢复为 0 笔，所有组的零计数也显式列示。

共读取 652205 行决策 trace。门槛表覆盖这些行的已记录终态理由；它不是未保存的逐个内部门槛执行轨迹。复核状态从前行保存状态及提交事件核对，未下单也可能消耗到期复核。没有外部 ack/cancel/queue 流，不能据此声称真实场所时钟已验证。

最差窗口固定为每个策略/成本组完整四小时日历的最差 ceil(5%×N)，临界值并列全部保留；每个窗口列出全部五币的原生持仓、cash/position value 变化和组合收益贡献。沿用原 resample_equity 的已知标记前填规则并记录 source_time/标记年龄；网格完整不代表底层行情无缺口。只是原模拟账户贡献，不是因果因子归因或信号 alpha。没有读取新的行情，也没有事后挑选一两个故事窗口。

仍缺逐个内部门槛、veto 前和二次取整后完整目标、真实 PIT/费用/盘口/延迟、完整试验史及未使用留出。任务的完整实证验收仍未完成；所有新历史策略回放、真实收益模型拟合、真实校准拟合、最终留出读取和真实订单均为 0。
~~~~

### artifacts/current_system_recent/20260908_v3/report.md

SHA-256：`7f6e747e8bc59be864dc55395b1921c35f0b5591ba79bd4c685bbb4bcce39be1`。其中测试数量与历史归档错误只代表该冻结时点；本次全仓验证见正文。


~~~~markdown
# 当前量化系统：最近六个月五币历史测试

评估区间：2026-03-08T00:00:00+00:00 至 2026-09-08T12:00:00+00:00（UTC，右端不含）。
北京时间为 2026-03-08 08:00 至 2026-09-08 20:00。末根完整4h K线收盘为 19:59:59.999；当前未完成K线不参与。
末端付费平仓参考为2026-09-08北京时间16:00（最后完整K线开盘），最终4小时保持现金；未使用20:00之后的价格。

固定主候选 F3：净收益 **6.07%**，最大回撤 **6.59%**，50,000 USDT 变为 **53,035.49 USDT**。研究结论仍为 `NO_PROVEN_ALPHA`，生产策略仍为 CASH。
缓冲比F2节省费用 94.73 USDT，但最终净利润少 340.84 USDT。8月单月增加4,161.88 USDT，高于全段净利润3,035.49 USDT，利润集中而非稳定逐月增长。

## 固定测试口径

BTC/ETH/BNB/SOL/XRP，各10,000 USDT，子账户独立，无跨币转资，无外部入金；4h决策、下一事件成交、现货LONG/FLAT。评估起点前365天仅用于因果指标预热，不计入收益。F3为此前已固定的主候选，不按本轮赢家重新选择。

F2为连续趋势且无缓冲；F3增加10%数量缓冲；F4固定10/40、20/80、40/160天等权信号预算；F5采用与F3相同的风险、缓冲和成本规则持有市场。每币风险目标20%年化是软目标，不是组合保证。BUY_HOLD复用原B1的99%入场目标，没有风险再平衡；它与低暴露策略承担的风险不同。

没有新收益模型、校准器或标准化器拟合。A3/A7没有近期冻结预测，未伪造预测或暗中重训。F0/F1的旧季度边界诊断不重复；本次重点是当前连续运行版本。

版本身份：本轮开始时冻结的R4，源HEAD为 `d8c6d4013097f6323ab8b7a424c860ba0ccbd62b`。回放期间工作区出现其他策略改动，均予保留；本报告不覆盖这些后续修改。已从 `implementation/` 隔离导入冻结源码，额外180次复现的完整结果与原180个场景逐项一致。21项冻结策略契约测试和8项近期入口测试通过；未将全仓旧测试数量冒充本轮执行数。

## 基准全成本结果

| 配置 | 净收益 | 期末USDT | 最大回撤 | 年化Sharpe | 平均资金暴露 | 闭合交易 | 胜率 | 总成本USDT |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 当前生产：现金 | 0.00% | 50,000.00 | 0.00% | — | 0.00% | 0 | — | 0.00 |
| 连续趋势、无缓冲 | 6.75% | 53,376.33 | 6.68% | 1.23 | 19.26% | 15 | 33.33% | 456.74 |
| R4 主候选：连续趋势＋10%缓冲 | 6.07% | 53,035.49 | 6.59% | 1.16 | 18.90% | 15 | 33.33% | 362.02 |
| 固定多周期趋势 | 2.83% | 51,413.42 | 3.45% | 1.01 | 8.84% | 15 | 26.67% | 161.23 |
| 同风险政策持有 | 10.02% | 55,011.42 | 14.32% | 1.04 | 49.02% | 5 | 100.00% | 302.90 |
| 买入持有（原 B1，99%目标） | 18.42% | 59,210.26 | 28.02% | 1.00 | 98.88% | 5 | 100.00% | 166.76 |

Sharpe按完整4h MTM权益计算、零无风险收益；半年年化值仅作诊断。闭合交易指完整flat-to-flat持仓周期，调仓成交不单算交易。

## F3 分币结果

| 币种 | 净收益 | 期末USDT | 最大回撤 | 平均资金暴露 | 闭合交易 | 成本USDT |
|---|---:|---:|---:|---:|---:|---:|
| BTCUSDT | -4.54% | 9,545.73 | 13.73% | 25.34% | 4 | 96.43 |
| ETHUSDT | 11.11% | 11,111.27 | 6.37% | 23.66% | 2 | 60.56 |
| BNBUSDT | 17.56% | 11,756.02 | 9.17% | 23.37% | 3 | 89.22 |
| SOLUSDT | 8.79% | 10,878.54 | 11.82% | 13.03% | 3 | 66.71 |
| XRPUSDT | -2.56% | 9,743.93 | 5.97% | 8.69% | 3 | 49.08 |

## 月度与近期切片

月度从同一连续资金路径切片，不清仓、不重置本金。3月和9月为不完整月份。

| 月份 | F3净收益 | F4净收益 | F5净收益 | 买入持有净收益 |
|---|---:|---:|---:|---:|
| 2026-03 | 0.00% | 0.00% | 0.05% | 1.94% |
| 2026-04 | -0.79% | -0.23% | 1.58% | 4.15% |
| 2026-05 | 0.15% | -0.59% | 0.88% | -0.90% |
| 2026-06 | -1.40% | -0.91% | -10.12% | -19.52% |
| 2026-07 | -1.82% | -0.55% | 2.09% | 6.66% |
| 2026-08 | 8.65% | 3.81% | 15.20% | 28.86% |
| 2026-09 | 1.50% | 1.34% | 1.51% | 1.75% |

| F3连续账户区间 | 区间净收益 | 区间内最大回撤 |
|---|---:|---:|
| 最近6个月 | 6.07% | 6.59% |
| 最近3个月 | 8.28% | 2.29% |
| 最近1个月 | 10.00% | 2.29% |

最近1/3个月保留此前的实际持仓和资金，不代表各自在起点重新投入50,000 USDT的独立回测。

## 成本压力与费用含义

基准单边手续费10 bps，半点差1 bps，滑点底值2 bps＋前一已完成K线NATR项，另计延迟不利1 bps与参与率冲击。现货没有资金费与借币成本。沿用代理精度、最小名义10 USDT及1%参与率上限；没有用当前费率折扣倒填历史。

| 配置 | 0×毛成本诊断 | 0.5× | 1× | 1.5× | 2× |
|---|---:|---:|---:|---:|---:|
| F2 | 7.73% | 7.24% | 6.75% | 6.27% | 5.79% |
| F3 | 6.84% | 6.46% | 6.07% | 5.69% | 5.31% |
| F4 | 3.16% | 2.99% | 2.83% | 2.66% | 2.50% |
| F5 | 10.68% | 10.35% | 10.02% | 9.70% | 9.37% |
| BUY_HOLD | 18.75% | 18.59% | 18.42% | 18.25% | 18.09% |

上表为各成本环境下完整重决策的资金回放，成交路径可能变化，不能把0×与1×的收益差全归为同成交费用。另有1.5×/2×冻结原订单的资金回放（保留拒单与库存约束），以及固定原成交的不可交易影子成本，详见CSV。

## 统计与证据边界

使用原R4共同UTC日轴的10,000次配对区块重采样，保留跨策略、跨币同时相关性；自动区块长度沿用已固定规则。统计只用完整UTC日，末尾半天收益与退出仍计入完整账户结果；统计差额与全段期末差额因此可能不同。

| 事前固定比较 | 日轴复合收益差 | 95%区间 | Holm校正p |
|---|---:|---|---:|
| F3-F2 | -0.71% | [-3.78%, 0.85%] | 1.0000 |
| F4-F3 | -3.27% | [-16.93%, 4.42%] | 1.0000 |
| F3-F5 | -3.95% | [-33.17%, 17.01%] | 1.0000 |
| F4-F5 | -7.22% | [-46.43%, 17.27%] | 1.0000 |
| F3-CASH | 6.14% | [-8.12%, 29.14%] | 1.0000 |

这六个月不是预先封存满12个月的最终留出集。固定存活五币不代表全市场可交易清单；历史账户费率、盘口排队和真实容量未验证。DSR/PBO所需完整独立试验历史仍不齐全，不能用本轮少量配置代替。正收益或单个较好的币种也不能自动证明alpha，亦未改变纸面/实盘准入。

## 验证与可复现材料

完成180次实际引擎运行。逐运行检查成本恒等式、非负现金、LONG/FLAT、权益=现金+持仓市值、严格下一事件成交、末端真实付费退出，以及保存结果重读。组合每个时点必须包含相同五币，累计资金与Decimal账本核对。

每币完整4h时间轴、预热与三周期就绪数量见 `data_quality.json`；来源页及SHA-256在 `source_manifest.json` / `raw/`。官方数据格式见 [Binance Kline 文档](https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints)。

`runs/`保存完整逐订单、逐成交、仓位、成本、权益与闭合交易JSON及决策追踪；`portfolio_summary.csv`、`per_asset.csv`、`monthly.csv`、`recent_windows.csv`、`same_fill_shadow_summary.csv`提供易读表格。`implementation/`保存运行源码，`effective_config.json`冻结参数与日期。验证记录见 `validation/`。

复现：使用新目录执行 `python -m scripts.run_recent_multi_asset_backtest prepare --output <new-dir>`，随后执行 `run`。精确重放本次日期须使用本目录保存的数据与冻结配置，不能用未来下载的新增日期冒充同一运行。

v1在配置序列化时失败；v2在回放初始化的严格Decimal解析时失败；均发生在引擎运行前，未产生收益试验。原失败目录和日志保留；v3只修正输入序列化适配，没有修改R4策略或引擎。

![权益与回撤](equity_and_drawdown.png)

## 自动本地归档

自动归档退出码2，未生成新提交。裸库 D:\Workspace\git\Personal--Quantitative_Trading.git 仍有 codex-archive 分支。
按 [local-git-remote/SKILL.md](C:/Users/SXD/.codex/skills/local-git-remote/SKILL.md) 的要求：
“已有非 main 归档或未指向 main 的归档 HEAD 必须保留并报错”，本次只停止归档，未迁移或删除历史。
源工作区 main 的并行改动与本轮成果均保留，未提交。完整记录见 validation/local_git_archive.json。
~~~~

## 附录 C：当前关键实现与失败测试

### src/aegisquant/research/strategies/buffered_target.py

来源：[src/aegisquant/research/strategies/buffered_target.py](https://github.com/tORHANSxd/AegisQuant/blob/main/src/aegisquant/research/strategies/buffered_target.py)；完整文件 SHA-256：`596b7fcdd31e48f7d0b35b9f477bbfd2e2c9c6fa8ce263af180079510b1837fc`。
以下为当前完整文件（1–259 行）。


~~~~python
"""R4 quantity buffer, adapted from the supplied reference without ledger side effects.

The caller retains precision, cash, fees, risk limits and pending-order management.
Input availability must cover every dependency. A target is never a booked fill.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from enum import StrEnum

ZERO = Decimal("0")
ONE = Decimal("1")


def _number(name: str, value: object) -> None:
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} 必须是 Decimal，禁止隐式接收 float")
    if not value.is_finite() or value < ZERO:
        raise ValueError(f"{name} 必须有限且非负")


def _utc(name: str, value: object) -> None:
    if not isinstance(value, datetime) or value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} 必须是明确 UTC 的 datetime")


class Action(StrEnum):
    HOLD = "HOLD"
    REQUEST_TARGET = "REQUEST_TARGET"
    RECONCILE_PENDING = "RECONCILE_PENDING"
    BLOCKED = "BLOCKED"


def _positive_interval(value: object) -> None:
    if not isinstance(value, timedelta) or value <= timedelta(0):
        raise ValueError("review_interval 必须是正 timedelta")


@dataclass(frozen=True)
class BufferPolicy:
    relative_half_width: Decimal = Decimal("0.10")
    review_interval: timedelta = timedelta(days=1)
    restore_half_width: Decimal | None = None
    reduce_half_width: Decimal | None = None
    absolute_weight_floor: Decimal = ZERO

    def __post_init__(self) -> None:
        _number("relative_half_width", self.relative_half_width)
        if self.relative_half_width > ONE:
            raise ValueError("缓冲半宽不得超过参考数量")
        _positive_interval(self.review_interval)
        for name in ("restore_half_width", "reduce_half_width", "absolute_weight_floor"):
            value = getattr(self, name)
            if value is not None:
                _number(name, value)
                if value > ONE:
                    raise ValueError(f"{name} 不得超过 1")


@dataclass(frozen=True)
class Snapshot:
    decision_time: datetime
    available_time: datetime
    current_quantity: Decimal
    raw_target_quantity: Decimal
    reference_quantity: Decimal
    hard_max_quantity: Decimal
    trend_active: bool
    market_executable: bool = True
    hard_exit: bool = False
    pending_order_count: int = 0
    last_regular_review: datetime | None = None
    regular_review_due_override: bool | None = None
    equity_quantity: Decimal | None = None

    def __post_init__(self) -> None:
        _utc("decision_time", self.decision_time)
        _utc("available_time", self.available_time)
        if self.available_time > self.decision_time:
            raise ValueError("输入依赖尚不可用")
        for key in (
            "current_quantity",
            "raw_target_quantity",
            "reference_quantity",
            "hard_max_quantity",
        ):
            _number(key, getattr(self, key))
        for key in ("trend_active", "market_executable", "hard_exit"):
            if type(getattr(self, key)) is not bool:
                raise TypeError(f"{key} 必须是 bool")
        if type(self.pending_order_count) is not int or self.pending_order_count < 0:
            raise ValueError("pending_order_count 必须是非负整数")
        if (
            self.regular_review_due_override is not None
            and type(self.regular_review_due_override) is not bool
        ):
            raise TypeError("regular_review_due_override 必须是 bool 或 None")
        if self.last_regular_review is not None:
            _utc("last_regular_review", self.last_regular_review)
            if self.last_regular_review > self.decision_time:
                raise ValueError("上次调仓检查时间不能来自未来")
        if self.raw_target_quantity > ZERO and self.reference_quantity == ZERO:
            raise ValueError("正目标数量需要正参考数量")
        if self.equity_quantity is not None:
            _number("equity_quantity", self.equity_quantity)
            if self.equity_quantity == ZERO:
                raise ValueError("equity_quantity 必须为正")


@dataclass(frozen=True)
class Decision:
    action: Action
    target_quantity: Decimal | None
    reason: str
    regular_review_performed: bool = False
    lower_band: Decimal | None = None
    upper_band: Decimal | None = None


DEFAULT_BUFFER_POLICY = BufferPolicy()


def decide_buffered_target(
    snapshot: Snapshot, policy: BufferPolicy = DEFAULT_BUFFER_POLICY
) -> Decision:
    """Buffer ordinary resizes, preserving entry, trend exits and hard limits.

    Pass the original scheduler's review decision through the explicit override.
    RECONCILE_PENDING asks the existing order manager to wait, reuse or cancel as
    appropriate; it never erases intervening fills or unconditionally cancels.
    """
    s = snapshot
    if not s.market_executable:
        return Decision(Action.BLOCKED, None, "NO_EXECUTABLE_MARKET")
    if s.pending_order_count:
        return Decision(Action.RECONCILE_PENDING, None, "PENDING_ORDER_RECONCILIATION")

    def result(
        target: Decimal,
        reason: str,
        *,
        reviewed: bool = False,
        lower: Decimal | None = None,
        upper: Decimal | None = None,
    ) -> Decision:
        if target < ZERO or (target > s.hard_max_quantity and target != s.current_quantity):
            raise AssertionError("参考目标违反硬数量约束")
        action = Action.HOLD if target == s.current_quantity else Action.REQUEST_TARGET
        return Decision(action, target, reason, reviewed, lower, upper)

    if s.hard_exit:
        return result(ZERO, "HARD_EXIT")
    if not s.trend_active:
        return result(ZERO, "TREND_EXIT_OR_FLAT")
    if s.current_quantity > s.hard_max_quantity:
        return result(s.hard_max_quantity, "HARD_CAP_REDUCTION")

    target = min(s.raw_target_quantity, s.hard_max_quantity)
    if s.current_quantity == ZERO:
        return result(target, "NEW_TREND_ENTRY" if target else "ZERO_RISK_BUDGET")

    due = s.regular_review_due_override
    if due is None:
        due = (
            s.last_regular_review is None
            or s.decision_time - s.last_regular_review >= policy.review_interval
        )
    if not due:
        return result(s.current_quantity, "REGULAR_REVIEW_NOT_DUE")
    if target == ZERO:
        return result(ZERO, "SCHEDULED_ZERO_RISK_TARGET", reviewed=True)

    with localcontext() as ctx:
        ctx.prec = 50
        if policy.absolute_weight_floor and s.equity_quantity is None:
            raise ValueError("绝对权重缓冲需要 equity_quantity")
        floor = (s.equity_quantity or ZERO) * policy.absolute_weight_floor
        restore = policy.restore_half_width
        reduce = policy.reduce_half_width
        lower_width = max(
            floor,
            s.reference_quantity * (policy.relative_half_width if restore is None else restore),
        )
        upper_width = max(
            floor, s.reference_quantity * (policy.relative_half_width if reduce is None else reduce)
        )
        lower = max(ZERO, target - lower_width)
        upper = min(s.hard_max_quantity, target + upper_width)
        if s.current_quantity < lower:
            return result(lower, "BUFFER_RISK_RESTORE", reviewed=True, lower=lower, upper=upper)
        if s.current_quantity > upper:
            return result(upper, "BUFFER_RISK_REDUCE", reviewed=True, lower=lower, upper=upper)
        return result(s.current_quantity, "INSIDE_BUFFER", reviewed=True, lower=lower, upper=upper)


@dataclass(frozen=True)
class RiskResizePolicy:
    """Opt-in research settings; the R4 policy and its order clock stay frozen."""

    smoothing_half_life: timedelta = timedelta(days=5)
    review_interval: timedelta = timedelta(days=2)
    minimum_weight_change: Decimal = Decimal("0.03")
    minimum_notional: Decimal = Decimal("50")
    cost_benefit_lambda: Decimal = ONE

    def __post_init__(self) -> None:
        _positive_interval(self.smoothing_half_life)
        _positive_interval(self.review_interval)
        for name in ("minimum_weight_change", "minimum_notional", "cost_benefit_lambda"):
            _number(name, getattr(self, name))
        if self.minimum_weight_change > ONE or self.cost_benefit_lambda == ZERO:
            raise ValueError("invalid risk resize weight or cost-benefit lambda")


@dataclass
class TargetSmoother:
    """Elapsed-time EWMA of observed targets; callers reset on gaps and hard exits."""

    time: datetime | None = None
    weight: Decimal | None = None

    def update(self, time: datetime, target: Decimal, half_life: timedelta) -> Decimal:
        _utc("time", time)
        _number("target", target)
        _positive_interval(half_life)
        if target > ONE or (self.time is not None and time <= self.time):
            raise ValueError("smoother requires increasing time and long/flat weights")
        with localcontext() as ctx:
            ctx.prec = 50
            if self.time is None or self.weight is None:
                weight = target
            else:
                elapsed = Decimal(str((time - self.time).total_seconds()))
                decay = Decimal("0.5") ** (elapsed / Decimal(str(half_life.total_seconds())))
                weight = decay * self.weight + (ONE - decay) * target
        self.time, self.weight = time, weight
        return weight


def rebalance_risk_benefit(
    current: Decimal, proposed: Decimal, target: Decimal, volatility: Decimal, horizon: timedelta
) -> Decimal:
    """Equity-normalized reduction in variance tracking loss over one review interval.

    This is a preregistered risk-utility proxy, not a forecast of trading alpha.
    Compare it with incremental execution cost / equity, never a round-trip rate.
    """
    for name, value in (("current", current), ("proposed", proposed), ("target", target)):
        _number(name, value)
        if value > ONE:
            raise ValueError("risk benefit requires long/flat weights")
    _number("volatility", volatility)
    _positive_interval(horizon)
    years = Decimal(str(horizon.total_seconds())) / Decimal("31557600")
    improvement = (current - target) ** 2 - (proposed - target) ** 2
    return max(ZERO, improvement * volatility**2 * years / 2)
~~~~

### src/aegisquant/portfolio/optimizer.py

来源：[src/aegisquant/portfolio/optimizer.py](https://github.com/tORHANSxd/AegisQuant/blob/main/src/aegisquant/portfolio/optimizer.py)；完整文件 SHA-256：`5cb1aed0a371b608fa71007edce183429f6e488ebfa217942b33efab8457031a`。
以下为当前完整文件（1–494 行）。


~~~~python
"""Conservative robust portfolio projection with hard post-condition checks."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from decimal import ROUND_DOWN, Decimal

from aegisquant.data.hashing import canonical_sha256
from aegisquant.domain.identifiers import InstrumentId, ProposalId
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import canonical_result
from aegisquant.portfolio.models import (
    CovarianceEstimate,
    ExposureConstraint,
    ExposureDimension,
    NormalizedSignal,
    PortfolioConstructionPolicy,
    PortfolioLeg,
    PortfolioProposal,
    SignalInput,
    TargetQuantityAdjustment,
)
from aegisquant.portfolio.transition_costs import legacy_impact_model

ZERO = Decimal("0")
ONE = Decimal("1")


def target_quantity_adjustment(
    *,
    target_quantity: Decimal,
    current_quantity: Decimal,
    signed_pending_quantity: Decimal,
    price: Decimal,
    quantity_step: Decimal,
    minimum_notional: Decimal,
    minimum_economic_notional: Decimal = ZERO,
) -> TargetQuantityAdjustment:
    if (
        min(target_quantity, current_quantity, minimum_notional, minimum_economic_notional) < 0
        or min(price, quantity_step) <= 0
    ):
        raise ValueError("target adjustment requires valid long/flat quantities and market rules")
    delta = target_quantity - current_quantity - signed_pending_quantity
    conflict = delta * signed_pending_quantity < 0
    if conflict:
        quantity, reason = ZERO, "CANCEL_OPPOSING_PENDING_THEN_RECOMPUTE_FROM_ACK"
    else:
        rounded = (abs(delta) / quantity_step).to_integral_value(
            rounding=ROUND_DOWN
        ) * quantity_step
        quantity = rounded if delta > 0 else -rounded
        reason = "TARGET_MINUS_CURRENT_MINUS_PENDING"
        if abs(quantity) * price < max(minimum_notional, minimum_economic_notional):
            quantity, reason = ZERO, "BELOW_MINIMUM_ECONOMIC_REBALANCE"
    return TargetQuantityAdjustment(
        target_quantity=target_quantity,
        current_quantity=current_quantity,
        signed_pending_quantity=signed_pending_quantity,
        signed_order_quantity=canonical_result(quantity),
        cancel_pending_first=conflict,
        reason=reason,
    )


def _clip_unit(value: Decimal) -> Decimal:
    return max(Decimal("-1"), min(ONE, value))


def normalize_signal(signal: SignalInput, policy: PortfolioConstructionPolicy) -> NormalizedSignal:
    clipped = _clip_unit(signal.raw_score)
    discounted = canonical_result(clipped * signal.confidence)
    uncertainty_haircut = ONE - policy.uncertainty_penalty * (ONE - signal.confidence)
    robust = canonical_result(discounted * uncertainty_haircut)
    in_zone = abs(robust) < policy.no_trade_zone
    reasons: list[str] = []
    if clipped != signal.raw_score:
        reasons.append("AQ-PORTFOLIO-SIGNAL-CLIPPED")
    if signal.confidence < ONE:
        reasons.append("AQ-PORTFOLIO-CONFIDENCE-DISCOUNT")
    if in_zone:
        robust = ZERO
        reasons.append("AQ-PORTFOLIO-NO-TRADE-ZONE")
    return NormalizedSignal(
        signal=signal,
        clipped_score=clipped,
        discounted_score=discounted,
        robust_score=robust,
        in_no_trade_zone=in_zone,
        reason_codes=tuple(reasons),
    )


def _portfolio_variance(weights: list[Decimal], matrix: tuple[tuple[Decimal, ...], ...]) -> Decimal:
    value = sum(
        (
            weights[row] * matrix[row][column] * weights[column]
            for row in range(len(weights))
            for column in range(len(weights))
        ),
        start=ZERO,
    )
    if value < 0:
        raise ValueError("AQ-PORTFOLIO-NEGATIVE-VARIANCE")
    return canonical_result(value)


def _dimension_key(signal: SignalInput, dimension: ExposureDimension) -> str | None:
    return {
        ExposureDimension.ASSET: str(signal.asset_id),
        ExposureDimension.CONTRACT: str(signal.instrument_id),
        ExposureDimension.STRATEGY: str(signal.strategy_id),
        ExposureDimension.SLEEVE: signal.sleeve_id,
        ExposureDimension.VENUE: str(signal.venue_id),
        ExposureDimension.STABLECOIN: (
            str(signal.stablecoin_id) if signal.stablecoin_id is not None else None
        ),
        ExposureDimension.CORRELATION_CLUSTER: signal.correlation_cluster_id,
    }[dimension]


def _scale_all(weights: list[Decimal], maximum: Decimal) -> None:
    gross = sum((abs(item) for item in weights), start=ZERO)
    if gross > maximum:
        scale = maximum / gross
        for index, value in enumerate(weights):
            weights[index] = canonical_result(value * scale)


def _apply_group_constraints(
    *,
    weights: list[Decimal],
    signals: tuple[SignalInput, ...],
    constraints: tuple[ExposureConstraint, ...],
    reasons: list[list[str]],
) -> None:
    for constraint in constraints:
        members = [
            index
            for index, signal in enumerate(signals)
            if _dimension_key(signal, constraint.dimension) == constraint.key
        ]
        if not members:
            continue
        gross = sum((abs(weights[index]) for index in members), start=ZERO)
        if gross <= constraint.maximum_absolute_weight:
            continue
        scale = constraint.maximum_absolute_weight / gross if gross > ZERO else ZERO
        for index in members:
            weights[index] = canonical_result(weights[index] * scale)
            reasons[index].append(
                f"AQ-PORTFOLIO-{constraint.dimension.value}-CONSTRAINT:{constraint.key}"
            )


def _capacity_weight(
    signal: SignalInput, *, nav: Decimal, policy: PortfolioConstructionPolicy
) -> Decimal:
    if signal.average_daily_notional == ZERO:
        return ZERO
    participation = policy.maximum_participation
    curve = signal.impact_model or legacy_impact_model(signal.impact_coefficient_bps, capacity=True)
    participation = min(participation, curve.participation_for_impact(policy.maximum_impact_bps))
    return canonical_result(signal.average_daily_notional * participation / nav)


def _apply_capacity(
    *,
    weights: list[Decimal],
    signals: tuple[SignalInput, ...],
    nav: Decimal,
    policy: PortfolioConstructionPolicy,
    reasons: list[list[str]],
) -> list[Decimal]:
    capacities: list[Decimal] = []
    for index, signal in enumerate(signals):
        capacity = _capacity_weight(signal, nav=nav, policy=policy)
        capacities.append(capacity)
        delta = weights[index] - signal.current_weight
        if abs(delta) > capacity:
            direction = ONE if delta > ZERO else Decimal("-1")
            weights[index] = canonical_result(signal.current_weight + direction * capacity)
            reasons[index].append("AQ-PORTFOLIO-CAPACITY-CONSTRAINT")
    return capacities


def _apply_turnover(
    *,
    weights: list[Decimal],
    signals: tuple[SignalInput, ...],
    maximum_turnover: Decimal,
    reasons: list[list[str]],
) -> None:
    deltas = [
        weight - signal.current_weight for weight, signal in zip(weights, signals, strict=True)
    ]
    turnover = sum((abs(item) for item in deltas), start=ZERO)
    if turnover <= maximum_turnover:
        return
    scale = maximum_turnover / turnover if turnover > ZERO else ZERO
    remaining = maximum_turnover
    for index, signal in enumerate(signals):
        scaled_delta = canonical_result(deltas[index] * scale)
        magnitude = min(abs(scaled_delta), remaining)
        direction = ONE if scaled_delta > ZERO else Decimal("-1")
        candidate = canonical_result(signal.current_weight + direction * magnitude)
        realized = abs(candidate - signal.current_weight)
        if realized > remaining:
            candidate = signal.current_weight
            realized = ZERO
        weights[index] = candidate
        remaining = canonical_result(max(ZERO, remaining - realized))
        reasons[index].append("AQ-PORTFOLIO-TURNOVER-CONSTRAINT")


def _assert_constraints(
    *,
    weights: list[Decimal],
    signals: tuple[SignalInput, ...],
    capacities: list[Decimal],
    policy: PortfolioConstructionPolicy,
    covariance_matrix: tuple[tuple[Decimal, ...], ...],
) -> None:
    gross = sum((abs(item) for item in weights), start=ZERO)
    if gross > policy.maximum_gross_weight:
        raise ValueError("AQ-PORTFOLIO-GROSS-POSTCONDITION")
    turnover = sum(
        (
            abs(weight - signal.current_weight)
            for weight, signal in zip(weights, signals, strict=True)
        ),
        start=ZERO,
    )
    if turnover > policy.maximum_turnover:
        raise ValueError("AQ-PORTFOLIO-TURNOVER-POSTCONDITION")
    for index, signal in enumerate(signals):
        if abs(weights[index] - signal.current_weight) > capacities[index]:
            raise ValueError("AQ-PORTFOLIO-CAPACITY-POSTCONDITION")
    for constraint in policy.exposure_constraints:
        gross = sum(
            (
                abs(weights[index])
                for index, signal in enumerate(signals)
                if _dimension_key(signal, constraint.dimension) == constraint.key
            ),
            start=ZERO,
        )
        if gross > constraint.maximum_absolute_weight:
            raise ValueError("AQ-PORTFOLIO-GROUP-POSTCONDITION")
    variance = _portfolio_variance(weights, covariance_matrix)
    if variance.sqrt() > policy.volatility_target:
        raise ValueError("AQ-PORTFOLIO-VOLATILITY-POSTCONDITION")


def build_portfolio_proposal(
    *,
    proposal_id: ProposalId,
    signals: tuple[SignalInput, ...],
    covariance: CovarianceEstimate,
    policy: PortfolioConstructionPolicy,
    portfolio_nav: Decimal,
    as_of_time: UtcDateTime,
    created_at: UtcDateTime,
    validity_seconds: int = 60,
    raw_target_weights: Mapping[InstrumentId, Decimal] | None = None,
    hard_risk_reduction: bool = False,
) -> PortfolioProposal:
    """Build a proposal by conservative projections; hard conflicts fail closed."""

    if not signals or len({item.instrument_id for item in signals}) != len(signals):
        raise ValueError("portfolio signals must be non-empty and instrument-unique")
    if portfolio_nav <= ZERO or not portfolio_nav.is_finite():
        raise ValueError("portfolio NAV must be positive and finite")
    if covariance.available_at > as_of_time:
        raise ValueError("AQ-PORTFOLIO-FUTURE-COVARIANCE")
    if created_at < as_of_time or validity_seconds <= 0:
        raise ValueError("portfolio proposal timing is invalid")
    if hard_risk_reduction and raw_target_weights is None:
        raise ValueError("hard reduction requires explicit existing targets")
    if raw_target_weights is not None:
        if (
            set(raw_target_weights) != {signal.instrument_id for signal in signals}
            or any(not value.is_finite() or value < ZERO for value in raw_target_weights.values())
            or any(signal.current_weight < ZERO for signal in signals)
        ):
            raise ValueError("AQ-PORTFOLIO-RAW-TARGET-COVERAGE-OR-LONG-FLAT")
        if hard_risk_reduction and any(
            raw_target_weights[signal.instrument_id] > signal.current_weight for signal in signals
        ):
            raise ValueError("AQ-PORTFOLIO-HARD-REDUCTION-CANNOT-INCREASE")
    asset_index = {asset_id: index for index, asset_id in enumerate(covariance.asset_ids)}
    if any(signal.asset_id not in asset_index for signal in signals):
        raise ValueError("every signal asset requires covariance coverage")
    budget_by_asset = {item.asset_id: item.maximum_risk_share for item in policy.risk_budgets}
    if any(signal.asset_id not in budget_by_asset for signal in signals):
        raise ValueError("every signal asset requires a risk budget")
    normalized = tuple(
        normalize_signal(signal, policy)
        if raw_target_weights is None
        else NormalizedSignal(
            signal=signal,
            clipped_score=ZERO,
            discounted_score=ZERO,
            robust_score=ZERO,
            in_no_trade_zone=False,
            reason_codes=("AQ-PORTFOLIO-EXISTING-TARGET-NO-RETURN-FORECAST",),
        )
        for signal in signals
    )
    weights: list[Decimal] = []
    reasons = [list(item.reason_codes) for item in normalized]
    for item in normalized:
        if raw_target_weights is not None:
            diagonal = covariance.matrix[asset_index[item.signal.asset_id]][
                asset_index[item.signal.asset_id]
            ]
            if (
                diagonal <= ZERO
                and raw_target_weights[item.signal.instrument_id] > item.signal.current_weight
            ):
                raise ValueError("AQ-PORTFOLIO-NONPOSITIVE-ASSET-VARIANCE")
            weights.append(raw_target_weights[item.signal.instrument_id])
            continue
        if item.in_no_trade_zone:
            weights.append(item.signal.current_weight)
            continue
        variance = covariance.matrix[asset_index[item.signal.asset_id]][
            asset_index[item.signal.asset_id]
        ]
        if variance <= ZERO:
            raise ValueError("AQ-PORTFOLIO-NONPOSITIVE-ASSET-VARIANCE")
        inverse_volatility = ONE / variance.sqrt()
        weight = item.robust_score * budget_by_asset[item.signal.asset_id] * inverse_volatility
        weights.append(canonical_result(weight))
    _scale_all(weights, policy.maximum_gross_weight)
    ordered_matrix = tuple(
        tuple(
            covariance.matrix[asset_index[row.asset_id]][asset_index[column.asset_id]]
            for column in signals
        )
        for row in signals
    )
    variance = _portfolio_variance(weights, ordered_matrix)
    volatility = variance.sqrt()
    if volatility > policy.volatility_target:
        scale = policy.volatility_target / volatility
        for index, value in enumerate(weights):
            weights[index] = canonical_result(value * scale)
            reasons[index].append("AQ-PORTFOLIO-VOLATILITY-TARGET")
    _apply_group_constraints(
        weights=weights,
        signals=signals,
        constraints=policy.exposure_constraints,
        reasons=reasons,
    )
    capacities = _apply_capacity(
        weights=weights,
        signals=signals,
        nav=portfolio_nav,
        policy=policy,
        reasons=reasons,
    )
    if not hard_risk_reduction:
        _apply_turnover(
            weights=weights,
            signals=signals,
            maximum_turnover=policy.maximum_turnover,
            reasons=reasons,
        )
    _scale_all(weights, policy.maximum_gross_weight)
    _apply_group_constraints(
        weights=weights,
        signals=signals,
        constraints=policy.exposure_constraints,
        reasons=reasons,
    )
    checked_policy = policy
    if hard_risk_reduction:
        # A hard exit can exceed ordinary turnover, but never available liquidity.
        capacities = _apply_capacity(
            weights=weights, signals=signals, nav=portfolio_nav, policy=policy, reasons=reasons
        )
        checked_policy = policy.model_copy(
            update={
                "maximum_turnover": max(
                    policy.maximum_turnover,
                    sum((abs(signal.current_weight) for signal in signals), start=ZERO),
                )
            }
        )
    try:
        _assert_constraints(
            weights=weights,
            signals=signals,
            capacities=capacities,
            policy=checked_policy,
            covariance_matrix=ordered_matrix,
        )
    except ValueError as error:
        if not hard_risk_reduction:
            raise
        if any(
            weight < ZERO
            or weight > signal.current_weight
            or abs(weight - signal.current_weight) > capacities[index]
            for index, (weight, signal) in enumerate(zip(weights, signals, strict=True))
        ):
            raise ValueError("AQ-PORTFOLIO-HARD-REDUCTION-LIQUIDITY-OR-DIRECTION") from error
        for values in reasons:
            values.append("AQ-PORTFOLIO-UNRESOLVED-BREACH:" + str(error))
    portfolio_variance = _portfolio_variance(weights, ordered_matrix)
    portfolio_volatility = portfolio_variance.sqrt()
    covariance_times_weight = [
        sum(
            (ordered_matrix[row][column] * weights[column] for column in range(len(weights))),
            start=ZERO,
        )
        for row in range(len(weights))
    ]
    legs: list[PortfolioLeg] = []
    for index, signal in enumerate(signals):
        delta = canonical_result(weights[index] - signal.current_weight)
        participation = (
            abs(delta) * portfolio_nav / signal.average_daily_notional
            if signal.average_daily_notional > ZERO
            else ZERO
        )
        curve = signal.impact_model or legacy_impact_model(
            signal.impact_coefficient_bps, capacity=True
        )
        impact = canonical_result(curve.impact_bps(participation))
        legs.append(
            PortfolioLeg(
                signal_id=signal.signal_id,
                asset_id=signal.asset_id,
                instrument_id=signal.instrument_id,
                strategy_id=signal.strategy_id,
                account_id=signal.account_id,
                sleeve_id=signal.sleeve_id,
                venue_id=signal.venue_id,
                stablecoin_id=signal.stablecoin_id,
                correlation_cluster_id=signal.correlation_cluster_id,
                current_weight=signal.current_weight,
                target_weight=weights[index],
                delta_weight=delta,
                normalized_signal=normalized[index].robust_score,
                expected_return_contribution=canonical_result(
                    weights[index] * signal.expected_return if raw_target_weights is None else ZERO
                ),
                marginal_variance_contribution=canonical_result(
                    weights[index] * covariance_times_weight[index]
                ),
                estimated_impact_bps=impact,
                capacity_weight=capacities[index],
                constraint_reasons=tuple(dict.fromkeys(reasons[index])),
            )
        )
    proposal_payload = {
        "proposal_id": str(proposal_id),
        "policy_version": policy.version,
        "covariance_sha256": covariance.estimate_sha256,
        "as_of_time": as_of_time.isoformat(),
        "created_at": created_at.isoformat(),
        "legs": [leg.model_dump(mode="json") for leg in legs],
    }
    gross = sum((abs(item.target_weight) for item in legs), start=ZERO)
    turnover = sum((abs(item.delta_weight) for item in legs), start=ZERO)
    expected_return = sum((item.expected_return_contribution for item in legs), start=ZERO)
    objective = canonical_result(
        expected_return
        - policy.uncertainty_penalty * portfolio_variance
        - sum((item.estimated_impact_bps * abs(item.delta_weight) for item in legs), start=ZERO)
        / Decimal("10000")
    )
    return PortfolioProposal(
        proposal_id=proposal_id,
        policy_version=policy.version,
        covariance_sha256=covariance.estimate_sha256,
        proposal_sha256=canonical_sha256(proposal_payload),
        as_of_time=as_of_time,
        created_at=created_at,
        valid_until=created_at + timedelta(seconds=validity_seconds),
        environment_stage=policy.environment_stage,
        legs=tuple(legs),
        expected_return=expected_return,
        expected_volatility=portfolio_volatility,
        gross_weight=gross,
        turnover=turnover,
        objective_value=objective,
        constraint_summary=tuple(
            sorted({reason for leg_reasons in reasons for reason in leg_reasons})
        ),
    )
~~~~

### artifacts/alpha_v5/20260908_research_churn_v3/implementation/src/aegisquant/portfolio/optimizer.py

来源：[artifacts/alpha_v5/20260908_research_churn_v3/implementation/src/aegisquant/portfolio/optimizer.py](https://github.com/tORHANSxd/AegisQuant/blob/main/artifacts/alpha_v5/20260908_research_churn_v3/implementation/src/aegisquant/portfolio/optimizer.py)；完整文件 SHA-256：`c52abbcaf1bbbb90715569a563fc85e57974f89e15ead33cc6db5d7e3bc033c1`。
`target_quantity_adjustment`，原文件第 28–62 行：


~~~~python
def target_quantity_adjustment(
    *,
    target_quantity: Decimal,
    current_quantity: Decimal,
    signed_pending_quantity: Decimal,
    price: Decimal,
    quantity_step: Decimal,
    minimum_notional: Decimal,
    minimum_economic_notional: Decimal = ZERO,
) -> TargetQuantityAdjustment:
    if (
        min(target_quantity, current_quantity, minimum_notional, minimum_economic_notional) < 0
        or min(price, quantity_step) <= 0
    ):
        raise ValueError("target adjustment requires valid long/flat quantities and market rules")
    delta = target_quantity - current_quantity - signed_pending_quantity
    conflict = delta * signed_pending_quantity < 0
    if conflict:
        quantity, reason = ZERO, "CANCEL_OPPOSING_PENDING_THEN_RECOMPUTE_FROM_ACK"
    else:
        rounded = (abs(delta) / quantity_step).to_integral_value(
            rounding=ROUND_DOWN
        ) * quantity_step
        quantity = rounded if delta > 0 else -rounded
        reason = "TARGET_MINUS_CURRENT_MINUS_PENDING"
        if abs(quantity) * price < max(minimum_notional, minimum_economic_notional):
            quantity, reason = ZERO, "BELOW_MINIMUM_ECONOMIC_REBALANCE"
    return TargetQuantityAdjustment(
        target_quantity=target_quantity,
        current_quantity=current_quantity,
        signed_pending_quantity=signed_pending_quantity,
        signed_order_quantity=canonical_result(quantity),
        cancel_pending_first=conflict,
        reason=reason,
    )
~~~~

### src/aegisquant/research/validation/cat_replay.py

来源：[src/aegisquant/research/validation/cat_replay.py](https://github.com/tORHANSxd/AegisQuant/blob/main/src/aegisquant/research/validation/cat_replay.py)；完整文件 SHA-256：`5d722264eb2b3d2f0366e425645fe759189ac468aa2f9f1b51dccafd30317e01`。
`load_completed_bars`，原文件第 111–168 行：


~~~~python
def load_completed_bars(
    path: Path,
    *,
    hours: int = 4,
    market_spec: CatMarket = DEFAULT_MARKET,
    strict_source: bool = False,
) -> tuple[BarEvent, ...]:
    """Discard incomplete buckets; never invent a missing market observation."""
    if hours not in (1, 4):
        raise ValueError("CAT supports only original hourly and declared four-hour bars")
    width = hours * 3_600_000
    buckets: dict[int, list[dict[str, str]]] = {}
    previous_millis: int | None = None
    with path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            millis = int(row["open_time_ms"])
            if strict_source:
                prices = [Decimal(row[key]) for key in ("open", "high", "low", "close")]
                volume = Decimal(row["base_volume"])
                if (
                    any(not p.is_finite() or p <= 0 for p in prices)
                    or not volume.is_finite()
                    or volume < 0
                    or prices[1] < max(prices[0], prices[3])
                    or prices[2] > min(prices[0], prices[3])
                    or (previous_millis is not None and millis <= previous_millis)
                ):
                    raise ValueError("invalid, duplicate or unordered source OHLCV")
                previous_millis = millis
            buckets.setdefault(millis // width * width, []).append(row)
    bars: list[BarEvent] = []
    for start, values in sorted(buckets.items()):
        values.sort(key=lambda row: int(row["open_time_ms"]))
        if [int(row["open_time_ms"]) for row in values] != [
            start + i * 3_600_000 for i in range(hours)
        ]:
            continue
        if any(int(row["close_time_ms"]) != int(row["open_time_ms"]) + 3_599_999 for row in values):
            # A prematurely closed source candle cannot certify a complete hour.
            # Keep the gap explicit so feature warmup and risk veto can see it.
            continue
        bars.append(
            BarEvent(
                event_id=BacktestEventId(f"{str(market_spec.base_asset).lower()}{hours}h-{start}"),
                instrument_id=market_spec.instrument_id,
                venue_id=VENUE,
                base_asset_id=market_spec.base_asset,
                quote_asset_id=USDT,
                event_time=datetime.fromtimestamp(start / 1000, UTC),
                available_time=datetime.fromtimestamp((start + width - 1) / 1000, UTC),
                open=Decimal(values[0]["open"]),
                high=max(Decimal(row["high"]) for row in values),
                low=min(Decimal(row["low"]) for row in values),
                close=Decimal(values[-1]["close"]),
                volume=sum((Decimal(row["base_volume"]) for row in values), Decimal("0")),
            )
        )
    return tuple(bars)
~~~~

`replay_cat`，原文件第 199–907 行：


~~~~python
def replay_cat(
    *,
    root: Path,
    spec: BacktestRunSpec,
    bars: tuple[BarEvent, ...],
    features: TrendFeatures,
    feature_indices: Mapping[datetime, int],
    trend_by_time: Mapping[datetime, bool],
    forecasts: Mapping[datetime, EconomicForecast],
    level: str,
    old_targets: Mapping[datetime, bool] | None = None,
    gate_policy: EconomicGatePolicy = DEFAULT_GATE_POLICY,
    cost_multiplier: Decimal = Decimal("1"),
    spread_multiplier: Decimal = Decimal("1"),
    slippage_multiplier: Decimal = Decimal("1"),
    volume_multiplier: Decimal = Decimal("1"),
    latency_multiplier: int = 1,
    omit_cost: str | None = None,
    fixed_orders: tuple[BacktestOrder, ...] | None = None,
    market_spec: CatMarket = DEFAULT_MARKET,
    audit_policy: CatAuditPolicy | None = None,
    risk_weight_caps: Mapping[datetime, Decimal] | None = None,
    buffer_policy: BufferPolicy | None = None,
    resize_policy: RiskResizePolicy | None = None,
    signal_fractions: Mapping[datetime, Decimal] | None = None,
    terminal_exit: bool = True,
    terminal_exit_reason: str = "PREREGISTERED_FOLD_END_NEXT_OPEN_EXIT",
) -> tuple[BacktestResult, list[dict[str, Any]]]:
    if len(bars) < 3 or min(cost_multiplier, spread_multiplier, slippage_multiplier) < 0:
        raise ValueError("CAT replay requires at least three bars and nonnegative costs")
    if not 0 < volume_multiplier <= 1 or latency_multiplier < 1:
        raise ValueError("invalid CAT stress assumptions")
    if (
        buffer_policy is not None or signal_fractions is not None or resize_policy is not None
    ) and (
        audit_policy is None
        or any(
            (
                audit_policy.switches.use_model_entry_filter,
                audit_policy.switches.use_cost_entry_gate,
                audit_policy.switches.use_probability_entry_gate,
                audit_policy.switches.use_uncertainty_entry_gate,
                audit_policy.switches.use_confidence_sizing,
                audit_policy.switches.use_model_economic_exit,
            )
        )
    ):
        raise ValueError("R4 extensions require the independent no-ML risk policy")
    if any(
        bar.instrument_id != market_spec.instrument_id
        or bar.base_asset_id != market_spec.base_asset
        or bar.quote_asset_id != USDT
        for bar in bars
    ):
        raise ValueError("CAT market bars and execution asset units differ")
    schedules: list[CostSchedule] = []
    execution = audit_policy.execution if audit_policy else None
    for n, bar in enumerate(bars):
        i = feature_indices[bar.available_time]
        prior_natr = float(features.values[max(0, i - 1), 9])
        known_natr = decimal(prior_natr) if np.isfinite(prior_natr) else Decimal("0")
        fee = (
            Decimal("0")
            if omit_cost == "fee"
            else execution.fee_bps
            if execution
            else Decimal("10")
        )
        spread = (
            Decimal("0")
            if omit_cost == "spread"
            else spread_multiplier * (execution.half_spread_bps if execution else 1)
        )
        slip = (
            Decimal("0")
            if omit_cost == "slippage"
            else (
                (execution.slippage_floor_bps if execution else Decimal("2"))
                + (execution.natr_slippage_coefficient * 10000 if execution else Decimal("100"))
                * known_natr
            )
            * slippage_multiplier
        )
        latency_adverse = (
            Decimal("0")
            if omit_cost == "latency"
            else Decimal(latency_multiplier) * (execution.latency_adverse_bps if execution else 1)
        )
        impact = (
            Decimal("0")
            if omit_cost == "impact"
            else execution.impact_coefficient_bps
            if execution
            else Decimal("25")
        )
        schedules.append(
            CostSchedule(
                cost_schedule_id=CostScheduleId(f"cat-cost-{n}"),
                version="cat-proxy-v2" if execution else "cat-proxy-v1",
                venue_id=VENUE,
                instrument_id=market_spec.instrument_id,
                effective_from=bar.event_time,
                effective_to=bars[n + 1].event_time if n + 1 < len(bars) else None,
                maker_fee_bps=fee * cost_multiplier,
                taker_fee_bps=fee * cost_multiplier,
                half_spread_bps=spread * cost_multiplier,
                slippage_bps=(slip + latency_adverse) * cost_multiplier,
                impact_coefficient_bps=impact * cost_multiplier,
                maximum_impact_bps=impact * cost_multiplier,
                funding_rate=Decimal("0"),
                borrow_rate_annual=Decimal("0"),
                settlement_fee_bps=Decimal("0"),
                participation_cap=execution.participation_cap if execution else Decimal("0.01"),
                source="PREREGISTERED_PROXY: previous completed bar NATR; no historical orderbook",
            )
        )
    rule = HistoricalInstrumentRule(
        instrument_rule_id=InstrumentRuleId("cat-rule-proxy-v1"),
        version="cat-rule-proxy-v1",
        instrument_id=market_spec.instrument_id,
        venue_id=VENUE,
        effective_from=bars[0].event_time,
        tick_size=market_spec.tick_size,
        step_size=market_spec.quantity_step,
        minimum_quantity=market_spec.quantity_step,
        minimum_notional=execution.minimum_notional if execution else Decimal("10"),
        trading_enabled=True,
        source="PREREGISTERED_PROXY_NOT_HISTORICAL_EXCHANGE_RULE_PROOF",
        approximation=f"{market_spec.base_asset} step and notional assumptions; venue history unverified",
    )
    engine = EventBacktestEngine(
        project_root=root,
        cost_book=HistoricalCostBook(schedules),
        rule_book=HistoricalRuleBook((rule,)),
        latency_policy=LatencyPolicy(
            version="cat-latency-v1",
            signal_ns=0,
            risk_ns=0,
            network_ns=(execution.latency_ns if execution else 100_000) * latency_multiplier,
            acknowledgement_ns=0,
            cancel_ns=100_000,
            source="preregistered proxy; bar execution cannot resolve intrabar latency",
        ),
    )
    decisions: list[dict[str, Any]] = []
    last_resize_day: object = None
    last_resize_time: datetime | None = None
    last_regular_review: datetime | None = None
    smoother = TargetSmoother()
    exit_decision_time = bars[-2].available_time

    def callback(context: BacktestDecisionContext) -> BacktestDecisionUpdate:
        nonlocal last_resize_day, last_resize_time, last_regular_review
        if not isinstance(context.event, BarEvent):
            raise TypeError("CAT expects completed bars")
        event = context.event
        time = event.available_time
        i = feature_indices[time]
        price = event.close
        held = context.position_quantity
        if context.equity <= 0 or held < 0 or context.cash < 0:
            raise ValueError("CAT long/flat cash conservation violated")
        trend = trend_by_time.get(time, False)
        target = held
        reason = "HOLD_CURRENT"
        q_long = hurdle = None
        details: dict[str, Any] = {}
        if terminal_exit and time >= exit_decision_time:
            target, reason = Decimal("0"), terminal_exit_reason
        elif level == "B0":
            target, reason = Decimal("0"), "CASH"
        elif audit_policy is not None:
            execution = audit_policy.execution
            forecast = forecasts.get(time)
            if forecast is not None and not features.valid[i]:
                # Full ML validity controls model use, not independent trend risk inputs.
                forecast = None
            natr_float = float(features.values[i, 9])
            vol_float = float(features.annualized_volatility[i])
            good = np.isfinite(natr_float) and np.isfinite(vol_float) and event.volume > 0
            natr = decimal(natr_float) if good else Decimal("0")
            vol = max(Decimal("0.000001"), decimal(vol_float)) if good else Decimal("1")
            active_gate = gate_policy
            if risk_weight_caps is not None:
                cap = risk_weight_caps.get(time, Decimal("0"))
                active_gate = gate_policy.model_copy(
                    update={"maximum_weight": min(gate_policy.maximum_weight, cap)}
                )
            risk_weight = (
                min(active_gate.maximum_weight, active_gate.target_volatility / vol)
                if audit_policy.switches.use_risk_sizing
                else active_gate.maximum_weight
            )
            raw_risk_weight = risk_weight
            if resize_policy is not None:
                good = good and vol_float > 0
                if (
                    not good
                    or not trend
                    or (smoother.time is not None and time - smoother.time != timedelta(hours=4))
                ):
                    smoother.time, smoother.weight = None, None
                if good and trend:
                    risk_weight = min(
                        active_gate.maximum_weight,
                        smoother.update(time, risk_weight, resize_policy.smoothing_half_life),
                    )
                    smoother.weight = risk_weight
            signal_fraction = (
                signal_fractions.get(time, Decimal("0"))
                if signal_fractions is not None
                else Decimal("1")
            )
            if not signal_fraction.is_finite() or not 0 <= signal_fraction <= 1:
                raise ValueError("R4 signal fractions must be within the existing risk budget")
            confidence = Decimal("1")
            if audit_policy.switches.use_confidence_sizing and forecast is not None:
                confidence = min(
                    Decimal("1"),
                    max(
                        Decimal("0"),
                        (forecast.p_net_positive - active_gate.p_enter)
                        / (active_gate.p_full_size - active_gate.p_enter),
                    ),
                )

            def estimated(buy: Decimal, sell: Decimal):
                return estimate_spot_transition_costs(
                    available_time=time,
                    natr=natr,
                    quote_volume=max(Decimal("0.000001"), event.volume * price),
                    order_notional=buy,
                    exit_order_notional=sell,
                    fee_bps=execution.fee_bps * cost_multiplier,
                    half_spread_bps=execution.half_spread_bps * spread_multiplier * cost_multiplier,
                    slippage_floor_bps=execution.slippage_floor_bps
                    * slippage_multiplier
                    * cost_multiplier,
                    natr_slippage_coefficient=execution.natr_slippage_coefficient
                    * slippage_multiplier
                    * cost_multiplier,
                    impact_coefficient_bps=execution.impact_coefficient_bps * cost_multiplier,
                    latency_adverse_bps=execution.latency_adverse_bps
                    * latency_multiplier
                    * cost_multiplier,
                    exit_latency_adverse_bps=execution.latency_adverse_bps
                    * latency_multiplier
                    * cost_multiplier,
                )

            held_value = held * price
            candidate = max(
                Decimal("0"),
                context.equity * risk_weight * signal_fraction * confidence - held_value,
            )
            costs = estimated(
                min(candidate, context.cash), held_value or min(candidate, context.cash)
            )
            # Reserve costs plus a declared fraction of observed NATR, never the next open.
            buy_factor = (
                1
                + costs.entry.total
                - costs.entry.fee
                + natr * execution.price_reserve_natr_fraction
            ) * (1 + costs.entry.fee)
            pending_buy = sum(
                (p.remaining_quantity for p in context.pending_orders if p.side is OrderSide.BUY),
                Decimal("0"),
            )
            reserved_cash = pending_buy * price * buy_factor
            affordable = max(Decimal("0"), context.cash - reserved_cash) / buy_factor
            entry_notional = min(candidate, affordable)
            costs = estimated(entry_notional, held_value or entry_notional)
            rebalance_cost = None
            if audit_policy.version == "cat-audit-r2":
                component_good = (
                    forecast is not None
                    and forecast.component_failure(
                        probability_required=audit_policy.switches.use_probability_entry_gate
                        or audit_policy.switches.use_confidence_sizing,
                        decision_time=time,
                        maximum_age_days=audit_policy.maximum_calibration_age_days,
                    )
                    is None
                )
                needs_model = any(
                    (
                        audit_policy.switches.use_model_entry_filter,
                        audit_policy.switches.use_cost_entry_gate,
                        audit_policy.switches.use_probability_entry_gate,
                        audit_policy.switches.use_uncertainty_entry_gate,
                        audit_policy.switches.use_confidence_sizing,
                        audit_policy.switches.use_model_economic_exit,
                    )
                )
                resize_target = (
                    context.equity * risk_weight * signal_fraction * confidence
                    if component_good or not needs_model
                    else min(held_value, context.equity * risk_weight)
                )
                resize_delta = resize_target - held_value
                incremental = estimated(abs(resize_delta), abs(resize_delta))
                rebalance_cost = incremental.entry if resize_delta >= 0 else incremental.exit
            permitted = (
                last_resize_time is None
                or (time - last_resize_time).total_seconds()
                >= audit_policy.rebalance_cooldown_seconds
            )
            if resize_policy is not None:
                permitted = (
                    last_regular_review is None
                    or time - last_regular_review >= resize_policy.review_interval
                )
                if permitted and good and trend and held > 0 and not context.pending_orders:
                    last_regular_review = time
            decision = decide_economic_transition(
                policy=active_gate,
                forecast=forecast,
                costs=costs,
                decision_time=time,
                current_weight=min(Decimal("1"), held_value / context.equity),
                trend_candidate=trend,
                trend_exit_confirmed=not trend,
                data_quality_passed=bool(good),
                risk_allows_entry=True,
                annualized_volatility=vol,
                resize_permitted=permitted,
                audit_policy=audit_policy,
                rebalance_cost=rebalance_cost,
                signal_budget_fraction=signal_fraction,
                risk_target_override=risk_weight if resize_policy is not None else None,
            )
            reason, q_long, hurdle = decision.reason, decision.q_long, decision.entry_hurdle
            if decision.action is not EconomicAction.HOLD_CURRENT:
                target = context.equity * decision.target_weight / price
                if target > held:
                    target = min(target, held + affordable / price)
            reference_qty = context.equity * risk_weight / price
            raw_target_qty = context.equity * decision.risk_target_weight * confidence / price
            buffer_reason = None
            lower = upper = None
            if buffer_policy is not None and reason == "COST_AWARE_RISK_REBALANCE":
                buffered = decide_buffered_target(
                    Snapshot(
                        decision_time=time,
                        available_time=time,
                        current_quantity=held,
                        raw_target_quantity=raw_target_qty,
                        reference_quantity=reference_qty,
                        hard_max_quantity=context.equity * active_gate.maximum_weight / price,
                        trend_active=trend,
                        pending_order_count=len(context.pending_orders),
                        regular_review_due_override=permitted,
                        equity_quantity=context.equity / price,
                    ),
                    buffer_policy,
                )
                buffer_reason, lower, upper = (
                    buffered.reason,
                    buffered.lower_band,
                    buffered.upper_band,
                )
                # A pending reconciliation falls through to the existing order manager,
                # using the original desired target; it is never an unconditional cancel.
                if buffered.target_quantity is not None:
                    target = buffered.target_quantity
                    if target > held:
                        target = min(target, held + affordable / price)
            resize_details: dict[str, Any] = {}
            if resize_policy is not None:
                resize_details = {
                    "unsmoothed_risk_weight": str(raw_risk_weight),
                    "smoothed_risk_weight": str(risk_weight),
                    "smoother_time": smoother.time,
                    "last_regular_review": last_regular_review,
                    "resize_gate_reason": None,
                    "rebalance_risk_benefit": None,
                    "rebalance_cost_equity_fraction": None,
                    "risk_benefit_definition": "HALF_VARIANCE_TRACKING_LOSS_REDUCTION_REVIEW_HORIZON",
                }
                if reason == "COST_AWARE_RISK_REBALANCE" and not context.pending_orders:
                    quantized = target_quantity_adjustment(
                        target_quantity=target,
                        current_quantity=held,
                        signed_pending_quantity=Decimal("0"),
                        price=price,
                        quantity_step=rule.step_size,
                        minimum_notional=rule.minimum_notional,
                        minimum_economic_notional=max(
                            rule.minimum_notional, resize_policy.minimum_notional
                        ),
                    )
                    target = held + quantized.signed_order_quantity
                    delta_notional = abs(target - held) * price
                    leg_costs = estimated(delta_notional, delta_notional)
                    leg = leg_costs.entry if target > held else leg_costs.exit
                    adverse = delta_notional * (leg.total - leg.fee)
                    direction = Decimal("1") if target > held else Decimal("-1")
                    cost_fraction = (
                        adverse + (delta_notional + direction * adverse) * leg.fee
                    ) / context.equity
                    benefit = rebalance_risk_benefit(
                        min(Decimal("1"), held_value / context.equity),
                        min(Decimal("1"), target * price / context.equity),
                        raw_risk_weight * signal_fraction,
                        vol,
                        resize_policy.review_interval,
                    )
                    resize_details.update(
                        rebalance_risk_benefit=str(benefit),
                        rebalance_cost_equity_fraction=str(cost_fraction),
                    )
                    veto = (
                        "MINIMUM_REBALANCE_DELTA"
                        if delta_notional / context.equity < resize_policy.minimum_weight_change
                        or delta_notional < resize_policy.minimum_notional
                        else "REBALANCE_COST_EXCEEDS_RISK_BENEFIT"
                        if benefit <= 0
                        or cost_fraction > resize_policy.cost_benefit_lambda * benefit
                        else "REBALANCE_RISK_BENEFIT_COVERS_COST"
                    )
                    resize_details["resize_gate_reason"] = veto
                    if veto != "REBALANCE_RISK_BENEFIT_COVERS_COST":
                        target = held
            calibration_through = (
                (forecast.residual_calibrated_through or forecast.calibrated_through)
                if forecast
                else None
            )
            details = {
                "forecast_status": "MISSING_FORECAST"
                if forecast is None
                else forecast.calibration_status.value,
                "missing_reason": "MARKET_OR_RISK_INPUT_INVALID"
                if not good
                else "MODEL_NOT_FITTED_OR_NO_VALID_FEATURE_ROW"
                if forecast is None
                else None,
                "feature_quality": "VALID" if features.valid[i] else "FULL_ML_FEATURES_INVALID",
                "raw_prediction": None,
                "mean_bias": None,
                "raw_prediction_missing_reason": "NOT_PERSISTED_IN_ORIGINAL_FROZEN_FORECAST",
                "corrected_prediction": str(forecast.expected_gross_return) if forecast else None,
                "p_net_positive": str(forecast.p_net_positive) if forecast else None,
                "residual_interval_width": str(forecast.q90_return - forecast.q10_return)
                if forecast
                else None,
                "uncertainty_definition": audit_policy.uncertainty_definition,
                "forecast_available_time": forecast.available_time if forecast else None,
                "calibration_end": forecast.calibrated_through if forecast else None,
                "entry_cost_estimate": str(costs.entry.total),
                "exit_cost_estimate": str(costs.exit.total),
                "entry_cost_notional": str(entry_notional),
                "exit_cost_notional": str(held_value or entry_notional),
                "holding_cost": str(costs.holding),
                "cost_lambda": str(active_gate.lambda_cost),
                "execution_buffer": str(active_gate.execution_uncertainty_buffer),
                "exit_hurdle": str(decision.exit_hurdle),
                "risk_only_weight": str(decision.risk_target_weight),
                "risk_vol_estimate": str(vol),
                "risk_target": str(active_gate.target_volatility),
                "raw_risk_weight": str(risk_weight),
                "raw_target_quantity": str(raw_target_qty),
                "reference_quantity": str(reference_qty),
                "hard_max_quantity": str(context.equity * active_gate.maximum_weight / price),
                "signal_budget_fraction": str(signal_fraction),
                "buffer_reason": buffer_reason,
                "buffer_lower": str(lower) if lower is not None else None,
                "buffer_upper": str(upper) if upper is not None else None,
                "last_resize_time_before_decision": last_resize_time,
                "confidence_multiplier": str(decision.alpha_confidence_multiplier),
                "signal_filter_pass": decision.signal_filter_pass,
                "cost_filter_pass": decision.cost_filter_pass,
                "probability_filter_pass": decision.probability_filter_pass,
                "uncertainty_filter_pass": decision.uncertainty_filter_pass,
                "reserved_cash": str(reserved_cash),
                "buy_reserve_factor": str(buy_factor),
                "rebalance_permitted": permitted,
                "enabled_switches": audit_policy.switches.model_dump_json(),
                "decision_value_kind": decision.decision_value_kind,
                "q10": str(forecast.q10_return) if forecast else None,
                "q50": str(forecast.q50_return) if forecast else None,
                "q90": str(forecast.q90_return) if forecast else None,
                "quantile_width": str(forecast.q90_return - forecast.q10_return)
                if forecast
                else None,
                "distribution_penalty": str(decision.distribution_penalty),
                "mean_estimation_uncertainty": None,
                "mean_estimation_uncertainty_status": "NOT_ESTIMATED_NOT_RESIDUAL_WIDTH",
                "point_forecast_status": forecast.point_forecast_status.value
                if forecast
                else "MODEL_MISSING",
                "residual_calibration_status": str(forecast.residual_calibration_status)
                if forecast and forecast.residual_calibration_status
                else "UNSPECIFIED",
                "probability_calibration_status": str(forecast.probability_calibration_status)
                if forecast and forecast.probability_calibration_status
                else "UNSPECIFIED",
                "calibration_age_days": (time - calibration_through).total_seconds() / 86400
                if calibration_through is not None
                else None,
                "calibration_expiry_policy": "NO_AGE_CUTOFF_DIAGNOSE_ONLY"
                if audit_policy.maximum_calibration_age_days is None
                else str(audit_policy.maximum_calibration_age_days),
                "risk_rebalance_cost_rate": str(rebalance_cost.total) if rebalance_cost else None,
                **resize_details,
            }
        elif level in {"B1", "B2", "B3"}:
            long = (
                (old_targets or {}).get(time, False) if level == "B2" else (level == "B1" or trend)
            )
            if not long:
                target, reason = Decimal("0"), "PRIMARY_SIGNAL_FLAT"
            elif held == 0:
                target, reason = context.equity * Decimal("0.99") / price, "PRIMARY_SIGNAL_LONG"
        else:
            forecast = forecasts.get(time)
            if forecast is None or not features.valid[i]:
                target, reason = Decimal("0"), "MISSING_CAUSAL_FORECAST_OR_DATA"
            else:
                costs = estimate_spot_transition_costs(
                    available_time=time,
                    natr=decimal(float(features.values[i, 9])),
                    quote_volume=event.volume * price,
                    order_notional=min(context.equity, context.cash),
                )
                day = time.date()
                decision = decide_economic_transition(
                    policy=gate_policy,
                    forecast=forecast,
                    costs=costs,
                    decision_time=time,
                    current_weight=min(Decimal("1"), held * price / context.equity),
                    trend_candidate=trend,
                    trend_exit_confirmed=not trend,
                    data_quality_passed=bool(features.valid[i]),
                    risk_allows_entry=True,
                    annualized_volatility=max(
                        Decimal("0.000001"), decimal(float(features.annualized_volatility[i]))
                    ),
                    probability_filter=level not in {"B4", "B5", "LIGHTGBM", "ELASTIC_NET"},
                    uncertainty_filter=level not in {"B4", "B5", "LIGHTGBM", "ELASTIC_NET"},
                    volatility_sizing=level == "B7",
                    resize_permitted=day != last_resize_day,
                )
                last_resize_day = day
                reason, q_long, hurdle = decision.reason, decision.q_long, decision.entry_hurdle
                if decision.action is not EconomicAction.HOLD_CURRENT:
                    target = context.equity * decision.target_weight * Decimal("0.99") / price
        adjustment = target_quantity_adjustment(
            target_quantity=target,
            current_quantity=held,
            signed_pending_quantity=context.signed_pending_quantity,
            price=price,
            quantity_step=rule.step_size,
            minimum_notional=rule.minimum_notional,
            minimum_economic_notional=rule.minimum_notional,
        )
        if audit_policy is not None and audit_policy.version == "cat-audit-r2":
            execution = audit_policy.execution
            known_natr = float(features.values[i, 9])
            if np.isfinite(known_natr) and event.volume > 0:
                notional = abs(adjustment.signed_order_quantity) * price
                increment = estimate_spot_transition_costs(
                    available_time=time,
                    natr=decimal(known_natr),
                    quote_volume=event.volume * price,
                    order_notional=notional,
                    exit_order_notional=notional,
                    fee_bps=execution.fee_bps * cost_multiplier,
                    half_spread_bps=execution.half_spread_bps * spread_multiplier * cost_multiplier,
                    slippage_floor_bps=execution.slippage_floor_bps
                    * slippage_multiplier
                    * cost_multiplier,
                    natr_slippage_coefficient=execution.natr_slippage_coefficient
                    * slippage_multiplier
                    * cost_multiplier,
                    impact_coefficient_bps=execution.impact_coefficient_bps * cost_multiplier,
                    latency_adverse_bps=execution.latency_adverse_bps
                    * latency_multiplier
                    * cost_multiplier,
                    exit_latency_adverse_bps=execution.latency_adverse_bps
                    * latency_multiplier
                    * cost_multiplier,
                )
                leg = increment.entry if adjustment.signed_order_quantity >= 0 else increment.exit
                adverse = notional * (leg.total - leg.fee)
                direction = Decimal("1") if adjustment.signed_order_quantity >= 0 else Decimal("-1")
                details.update(
                    {
                        "planned_increment_cost_rate": str(leg.total),
                        "planned_increment_cost_usdt": str(
                            adverse + (notional + direction * adverse) * leg.fee
                        ),
                        "planned_increment_fee_currency": "USDT",
                        "cost_estimate_available_time": time,
                        "estimate_uses_future_fill": False,
                    }
                )
        decisions.append(
            {
                "time": time,
                "known_close": str(price),
                "cash": str(context.cash),
                "current_quantity": str(held),
                "target_quantity": str(target),
                "pending_quantity": str(context.signed_pending_quantity),
                "reason": reason,
                "q_long": str(q_long) if q_long is not None else None,
                "entry_hurdle": str(hurdle) if hurdle is not None else None,
                "run_id": str(spec.run_id),
                "symbol": f"{market_spec.base_asset}USDT",
                "decision_time": time,
                "available_time": event.available_time,
                "trend_state": "LONG" if trend else "FLAT",
                "current_weight": str(held * price / context.equity),
                "final_weight": str(target * price / context.equity),
                "planned_order_notional": str(abs(adjustment.signed_order_quantity) * price),
                "signed_planned_quantity": str(adjustment.signed_order_quantity),
                "cancel_pending_first": adjustment.cancel_pending_first,
                "quantity_adjustment_reason": adjustment.reason,
                "unexecuted_target_residual": str(
                    target
                    - held
                    - context.signed_pending_quantity
                    - adjustment.signed_order_quantity
                ),
                "risk_escalation": (
                    "UNTRADEABLE_EXIT_RESIDUAL"
                    if target == 0
                    and held > 0
                    and adjustment.signed_order_quantity == 0
                    and not context.pending_orders
                    else None
                ),
                **details,
            }
        )
        if adjustment.cancel_pending_first:
            return BacktestDecisionUpdate(
                cancel_order_ids=tuple(p.backtest_order_id for p in context.pending_orders)
            )
        delta = adjustment.signed_order_quantity
        if delta == 0 or (terminal_exit and time == bars[-1].available_time):
            return BacktestDecisionUpdate()
        if audit_policy is not None:
            last_resize_time = time
        if resize_policy is not None:
            last_regular_review = time
        key = f"{spec.run_id}-{len(decisions)}"
        return BacktestDecisionUpdate(
            orders=(
                BacktestOrder(
                    backtest_order_id=BacktestOrderId(key),
                    client_order_id=ClientOrderId(key),
                    order_intent_id=OrderIntentId(key),
                    instrument_id=market_spec.instrument_id,
                    venue_id=VENUE,
                    side=OrderSide.BUY if delta > 0 else OrderSide.SELL,
                    order_type=OrderType.MARKET,
                    quantity=Quantity(amount=abs(delta), asset_id=market_spec.base_asset),
                    time_in_force=TimeInForce.IMMEDIATE_OR_CANCEL,
                    reduce_only=delta < 0,
                    decision_time=time,
                    submitted_at=time,
                ),
            )
        )

    market = tuple(b.model_copy(update={"volume": b.volume * volume_multiplier}) for b in bars)
    result = engine.run(
        spec=spec,
        instrument=cat_instrument(market_spec),
        market_events=market,
        orders=fixed_orders or (),
        decision_callback=callback if fixed_orders is None else None,
    )
    if abs(result.cost_identity_residual) >= Decimal("0.00000001"):
        raise ValueError("CAT cost identity did not close")
    by_order = {str(order.order.backtest_order_id): order for order in result.orders}
    for number, row in enumerate(decisions, 1):
        key = f"{spec.run_id}-{number}"
        order = by_order.get(key)
        fills = [fill for fill in result.fills if str(fill.backtest_order_id) == key]
        row.update(
            {
                "order_id": key if order else None,
                "actual_fill_notional": str(
                    sum((fill.cost_breakdown.gross_notional for fill in fills), Decimal("0"))
                ),
                "realized_execution_cost": str(
                    sum((fill.cost_breakdown.total for fill in fills), Decimal("0"))
                ),
                "rejection_reason": str(order.rejection_code)
                if order and order.rejection_code
                else None,
                "order_status": str(order.status) if order else "NO_ORDER",
                "outcome_fields_available_after_decision": True,
            }
        )
        if row.get("planned_increment_cost_usdt") is not None:
            row["realized_minus_planned_cost_usdt"] = str(
                Decimal(row["realized_execution_cost"])
                - Decimal(row["planned_increment_cost_usdt"])
            )
            row["cost_error_interpretation"] = (
                "estimate_vs_fill_quantity_next_open_liquidity; separate from accounting_identity"
            )
    return result, decisions
~~~~

### src/aegisquant/backtest/costs.py

来源：[src/aegisquant/backtest/costs.py](https://github.com/tORHANSxd/AegisQuant/blob/main/src/aegisquant/backtest/costs.py)；完整文件 SHA-256：`63b70b2fcd7cc6a2033210363df03d5892d51476f834a549f08484bd9de287fb`。
`execution_price_and_cost`，原文件第 122–237 行：


~~~~python
def execution_price_and_cost(
    *,
    order: BacktestOrder,
    fill_slice: FillSlice,
    schedule: CostSchedule,
    base_asset_id: AssetId,
    quote_asset_id: AssetId,
    contract_multiplier: Decimal = Decimal("1"),
    settlement_quantity: Decimal = Decimal("0"),
    liquidation_penalty_bps: Decimal = Decimal("0"),
    strict_evidence: bool = False,
    fee_account: FeeAccountState | None = None,
) -> tuple[Price, CostBreakdown]:
    """Apply explicit adverse spread, slippage and size impact to one fill slice."""
    quantity = fill_slice.quantity
    if contract_multiplier <= 0 or not 0 <= settlement_quantity <= quantity:
        raise ValueError("invalid execution multiplier or settlement quantity")
    if liquidation_penalty_bps < 0:
        raise ValueError("liquidation penalty cannot be negative")
    reference = fill_slice.reference_price
    if fill_slice.available_liquidity == 0:
        participation = Decimal("1")
    else:
        participation = min(Decimal("1"), quantity / fill_slice.available_liquidity)
    proof = schedule.evidence
    basis = fill_slice.reference
    if (proof is None) != (basis is None):
        raise ValueError("AQ-EXECUTION-MIXED-LEGACY-AND-VERSIONED-COST")
    curve = (
        proof.impact_model
        if proof is not None
        else legacy_impact_model(schedule.impact_coefficient_bps)
    )
    if basis is not None:
        if curve.horizon_seconds != basis.participation_window_seconds:
            raise ValueError("AQ-IMPACT-HORIZON-MISMATCH")
        participation = quantity * contract_multiplier * reference / basis.window_quote_turnover
    if strict_evidence and (
        proof is None
        or basis is None
        or proof.verified_kind != "HISTORICAL_ACCOUNT_EVIDENCE"
        or basis.evidence_kind != "HISTORICAL_MARKET_EVIDENCE"
        or curve.evidence_status != "VERIFIED"
        or proof.fee_terms is None
    ):
        raise ValueError("AQ-EXECUTION-EMPIRICAL-EVIDENCE-MISSING")
    impact_bps = min(schedule.maximum_impact_bps, curve.impact_bps(participation))
    is_taker = fill_slice.liquidity_role is LiquidityRole.TAKER
    spread_bps = schedule.half_spread_bps if is_taker else Decimal("0")
    slippage_bps = schedule.slippage_bps if is_taker else Decimal("0")
    if basis is not None:
        included = set(basis.included_cost_components)
        if "SPREAD" in included:
            spread_bps = Decimal("0")
        if "SLIPPAGE" in included:
            slippage_bps = Decimal("0")
        if "RESIDUAL_IMPACT" in included or (
            "VISIBLE_DEPTH" in included and curve.target == "TOTAL_PRICE_IMPACT"
        ):
            impact_bps = Decimal("0")
    adverse_bps = spread_bps + slippage_bps + impact_bps
    direction = Decimal("1") if order.side is OrderSide.BUY else Decimal("-1")
    execution = canonical_result(reference * (Decimal("1") + direction * adverse_bps / BPS))
    gross_notional = canonical_result(quantity * contract_multiplier * reference)
    execution_notional = canonical_result(quantity * contract_multiplier * execution)
    fee_bps = (
        schedule.maker_fee_bps
        if fill_slice.liquidity_role is LiquidityRole.MAKER
        else schedule.taker_fee_bps
    )
    native_fee = None
    if proof is not None and proof.fee_terms is not None:
        if fee_account is None:
            raise ValueError("AQ-EXECUTION-NATIVE-FEE-ACCOUNT-STATE-REQUIRED")
        native_fee = settle_execution_fee(
            terms=proof.fee_terms,
            fill_time=fill_slice.event_time,
            role=fill_slice.liquidity_role,
            side=order.side,
            quantity=quantity * contract_multiplier,
            execution_price=execution,
            base_asset_id=base_asset_id,
            quote_asset_id=quote_asset_id,
            available_balances=fee_account.available_balances,
            quote_fx=fee_account.quote_fx,
            fx_available_at=fee_account.fx_available_at,
        )
    breakdown = CostBreakdown(
        asset_id=quote_asset_id,
        gross_notional=gross_notional,
        fee=native_fee.quote_equivalent
        if native_fee is not None
        else canonical_result(execution_notional * fee_bps / BPS),
        spread=canonical_result(gross_notional * spread_bps / BPS),
        slippage=canonical_result(gross_notional * slippage_bps / BPS),
        impact=canonical_result(gross_notional * impact_bps / BPS),
        funding=Decimal("0"),
        borrow_interest=Decimal("0"),
        settlement_fee=canonical_result(
            settlement_quantity
            * contract_multiplier
            * execution
            * schedule.settlement_fee_bps
            / BPS
        ),
        liquidation_penalty=canonical_result(execution_notional * liquidation_penalty_bps / BPS),
        fee_settlement=native_fee,
    )
    return (
        Price(
            amount=execution,
            base_asset_id=base_asset_id,
            quote_asset_id=quote_asset_id,
        ),
        breakdown,
    )
~~~~

`settle_execution_fee`，原文件第 240–325 行：


~~~~python
def settle_execution_fee(
    *,
    terms: FeeTerms,
    fill_time: UtcDateTime,
    role: LiquidityRole,
    side: OrderSide,
    quantity: Decimal,
    execution_price: Decimal,
    base_asset_id: AssetId,
    quote_asset_id: AssetId,
    available_balances: Mapping[AssetId, Decimal],
    quote_fx: Mapping[AssetId, Decimal],
    fx_available_at: UtcDateTime,
) -> FeeSettlement:
    """Settle each partial fill separately; only the standard component is discounted."""
    if (
        not quantity.is_finite()
        or not execution_price.is_finite()
        or quantity <= 0
        or execution_price <= 0
        or fx_available_at > fill_time
    ):
        raise ValueError("AQ-EXECUTION-INVALID-FEE-OR-FUTURE-FX")
    if any(not value.is_finite() or value < 0 for value in available_balances.values()):
        raise ValueError("fee balances must be finite and nonnegative")
    normal_asset = (
        base_asset_id
        if terms.normal_fee_asset == "RECEIVED_ASSET" and side is OrderSide.BUY
        else quote_asset_id
    )
    standard = terms.standard.for_fill(role, side)
    other = terms.special.for_fill(role, side) + terms.tax.for_fill(role, side)
    notional = quantity * execution_price
    ordinary_quote = notional * (standard + other) / BPS
    active = (
        terms.discount_asset_id is not None
        and terms.standard_discount_fraction > 0
        and terms.discount_effective_from is not None
        and terms.discount_effective_from <= fill_time
        and (terms.discount_effective_to is None or fill_time < terms.discount_effective_to)
    )
    reason = (
        "DISCOUNT_NOT_EFFECTIVE" if terms.standard_discount_fraction > 0 and not active else None
    )
    # A rebate must never be reduced by a fee discount.
    discounted_quote = (
        notional
        * (standard - max(Decimal("0"), standard) * terms.standard_discount_fraction + other)
        / BPS
    )
    if active and terms.discount_asset_id is not None:
        fx = quote_fx.get(terms.discount_asset_id)
        if fx is None or not fx.is_finite() or fx <= 0:
            reason = "DISCOUNT_FX_UNAVAILABLE"
        elif discounted_quote <= 0:
            reason = "REBATE_USES_NORMAL_FEE_ASSET"
        elif available_balances.get(terms.discount_asset_id, Decimal("0")) < discounted_quote / fx:
            reason = "DISCOUNT_ASSET_BALANCE_INSUFFICIENT"
        else:
            return FeeSettlement(
                fee=Money(
                    amount=canonical_result(discounted_quote / fx), asset_id=terms.discount_asset_id
                ),
                quote_equivalent=canonical_result(discounted_quote),
                undiscounted_quote_equivalent=canonical_result(ordinary_quote),
                discount_applied=True,
                fallback_reason=None,
            )
    normal_fx = execution_price if normal_asset == base_asset_id else Decimal("1")
    native = canonical_result(ordinary_quote / normal_fx)
    received = (
        quantity
        if side is OrderSide.BUY and normal_asset == base_asset_id
        else notional
        if side is OrderSide.SELL
        else Decimal("0")
    )
    if native > available_balances.get(normal_asset, Decimal("0")) + received:
        raise ValueError("AQ-EXECUTION-NORMAL-FEE-ASSET-BALANCE-INSUFFICIENT")
    return FeeSettlement(
        fee=Money(amount=native, asset_id=normal_asset),
        quote_equivalent=canonical_result(ordinary_quote),
        undiscounted_quote_equivalent=canonical_result(ordinary_quote),
        discount_applied=False,
        fallback_reason=reason,
    )
~~~~

### src/aegisquant/backtest/fills.py

来源：[src/aegisquant/backtest/fills.py](https://github.com/tORHANSxd/AegisQuant/blob/main/src/aegisquant/backtest/fills.py)；完整文件 SHA-256：`c59c9af68c2a81a8465d93b7d4bb699a5e276e53491b187b214883c1c5ac7190`。
`EventLiquidityBudget`，原文件第 265–428 行：


~~~~python
class EventLiquidityBudget:
    """A shared window budget around decide_fills; caller commits only settled fills."""

    def __init__(self, window: ParticipationWindow, maximum_participation: Decimal) -> None:
        if not maximum_participation.is_finite() or not 0 <= maximum_participation <= 1:
            raise ValueError("invalid shared participation cap")
        self.window = window
        self.maximum_quote_notional = window.quote_turnover * maximum_participation
        self.used_quote_notional = Decimal("0")
        # ponytail: retain event/fill keys for one supplied window; rotate only after it closes.
        self._events: dict[str, str] = {}
        self._levels: dict[tuple[str, OrderSide, Decimal], Decimal] = {}
        self._prepared: set[str] = set()
        self._fills: dict[str, str] = {}
        self._order_filled: dict[str, Decimal] = {}

    def preview(
        self,
        *,
        order: BacktestOrder,
        event: MarketEvent,
        remaining: Decimal,
        arrival_at: UtcDateTime,
        cancel_effective_at: UtcDateTime | None = None,
        queue_ahead: Decimal | None = None,
        queue_source_sha256: str | None = None,
    ) -> ExecutionFillDecision:
        """Event wins an equal-time cancellation, matching the existing engine convention."""
        order_id = str(order.backtest_order_id)
        if (
            not remaining.is_finite()
            or remaining <= 0
            or arrival_at < order.submitted_at
            or remaining > order.quantity.amount - self._order_filled.get(order_id, Decimal("0"))
        ):
            raise ValueError("invalid execution remaining quantity or arrival clock")
        if (
            order.instrument_id != self.window.instrument_id
            or order.venue_id != self.window.venue_id
        ):
            raise ValueError("AQ-EXECUTION-PARTICIPATION-WINDOW-INSTRUMENT-MISMATCH")
        reason = (
            "ORDER_NOT_AT_VENUE"
            if event.event_time < arrival_at
            else "CANCEL_ALREADY_EFFECTIVE"
            if cancel_effective_at is not None and cancel_effective_at < event.event_time
            else "BAR_PROXY_ONLY"
            if isinstance(event, BarEvent)
            else "WINDOW_NOT_KNOWN"
            if self.window.available_at > event.available_time
            or self.window.end != event.event_time
            else None
        )
        if reason is not None:
            return ExecutionFillDecision((), remaining, reason)
        event_id = str(event.event_id)
        event_hash = canonical_sha256(event.model_dump(mode="json"))
        if event_id in self._events and self._events[event_id] != event_hash:
            raise ValueError("AQ-EXECUTION-CONFLICTING-MARKET-EVENT")
        self._events[event_id] = event_hash
        execution_event = event
        if isinstance(event, L2BookEvent):
            levels = event.asks if order.side is OrderSide.BUY else event.bids
            # Use the existing engine's residual-book convention to reach deeper levels.
            execution_event = event.model_copy(
                update={
                    "asks" if order.side is OrderSide.BUY else "bids": tuple(
                        level.model_copy(
                            update={
                                "quantity": self._levels.get(
                                    (event_id, order.side, level.price), level.quantity
                                )
                            }
                        )
                        for level in levels
                    )
                }
            )
        raw = decide_fills(
            order=order, event=execution_event, remaining=remaining, participation_cap=Decimal("1")
        )
        if any(item.liquidity_role is LiquidityRole.MAKER for item in raw):
            if queue_ahead is None or queue_source_sha256 is None:
                return ExecutionFillDecision((), remaining, "MAKER_QUEUE_UNKNOWN")
            ensure_sha256(queue_source_sha256, field_name="maker queue source hash")
            if not queue_ahead.is_finite() or queue_ahead < 0:
                raise ValueError("maker queue ahead must be finite and nonnegative")
        left_quote = self.maximum_quote_notional - self.used_quote_notional
        output: list[FillSlice] = []
        for item in raw:
            key = (event_id, order.side, item.reference_price)
            available = item.available_liquidity
            if item.liquidity_role is LiquidityRole.MAKER:
                available = max(Decimal("0"), available - (queue_ahead or Decimal("0")))
            self._levels.setdefault(key, available)
            quantity = min(item.quantity, self._levels[key], left_quote / item.reference_price)
            if quantity <= 0:
                continue
            kind = (
                "MAKER_LIMIT"
                if item.liquidity_role is LiquidityRole.MAKER
                else "DEPTH_VWAP"
                if isinstance(event, L2BookEvent)
                else "BBO"
            )
            reference = ExecutionReference(
                reference_price_kind=kind,
                included_cost_components=("SPREAD", "VISIBLE_DEPTH")
                if kind == "DEPTH_VWAP"
                else ("SPREAD",)
                if kind == "BBO"
                else (),
                source_sha256=event_hash,
                evidence_kind="SYNTHETIC_ONLY",
                participation_window_seconds=int(
                    (self.window.end - self.window.start).total_seconds()
                ),
                window_quote_turnover=self.window.quote_turnover,
            )
            selected = item.model_copy(update={"quantity": quantity, "reference": reference})
            output.append(selected)
            left_quote -= quantity * item.reference_price
        filled = sum((item.quantity for item in output), Decimal("0"))
        if order.time_in_force is TimeInForce.FILL_OR_KILL and filled < remaining:
            return ExecutionFillDecision((), remaining, "FOK_INSUFFICIENT_SHARED_LIQUIDITY")
        self._prepared.update(self._identity(order, selected) for selected in output)
        return ExecutionFillDecision(
            tuple(output),
            remaining - filled,
            "FILLED" if filled == remaining else "UNFILLED_RESIDUAL",
        )

    @staticmethod
    def _identity(order: BacktestOrder, item: FillSlice) -> str:
        return canonical_sha256(
            {"order": order.model_dump(mode="json"), "slice": item.model_dump(mode="json")}
        )

    def commit(self, *, fill_id: str, order: BacktestOrder, item: FillSlice) -> bool:
        """Idempotent consumption; opposite sides cannot net out window usage."""
        identity = self._identity(order, item)
        if fill_id in self._fills:
            if self._fills[fill_id] != identity:
                raise ValueError("AQ-EXECUTION-CONFLICTING-FILL-ID")
            return False
        if identity not in self._prepared:
            raise ValueError("AQ-EXECUTION-FILL-WAS-NOT-PREPARED")
        key = (str(item.source_event_id), order.side, item.reference_price)
        order_id = str(order.backtest_order_id)
        if self._order_filled.get(order_id, Decimal("0")) + item.quantity > order.quantity.amount:
            raise ValueError("AQ-EXECUTION-FILL-EXCEEDS-ORDER-QUANTITY")
        notional = item.quantity * item.reference_price
        if (
            item.quantity > self._levels[key]
            or self.used_quote_notional + notional > self.maximum_quote_notional
        ):
            raise ValueError("AQ-EXECUTION-STALE-PREVIEW-EXCEEDS-LIQUIDITY")
        self._levels[key] -= item.quantity
        self.used_quote_notional += notional
        self._fills[fill_id] = identity
        self._order_filled[order_id] = (
            self._order_filled.get(order_id, Decimal("0")) + item.quantity
        )
        return True
~~~~

### src/aegisquant/accounting/ledger.py

来源：[src/aegisquant/accounting/ledger.py](https://github.com/tORHANSxd/AegisQuant/blob/main/src/aegisquant/accounting/ledger.py)；完整文件 SHA-256：`0156449710a88645f45e9d68f470f2bd57336ce38d61ec2efc3b08b4e36b7bf3`。
`LedgerEngine._validate_native_spot_fee`，原文件第 377–418 行：


~~~~python
    def _validate_native_spot_fee(self, fill: Fill, instrument: AccountingInstrument) -> None:
        """V2 is funded long/flat spot; validate before any lot/chart mutation."""
        if any(lot.side is LotSide.SHORT for lot in self.open_lots(instrument.instrument_id)):
            raise ValueError("AQ-LEDGER-NATIVE-FEE-REQUIRES-LONG-FLAT-SPOT")
        balances: dict[AssetId, Decimal] = {}
        for balance in self.native_balances():
            definition = self.chart.definition(balance.account_id)
            if definition.role is AccountRole.CASH and definition.venue == instrument.venue:
                balances[balance.asset_id] = (
                    balances.get(balance.asset_id, Decimal("0")) + balance.amount
                )
        base_quantity = fill.quantity.amount * instrument.contract_multiplier
        notional = base_quantity * fill.price.amount
        buy = fill.side.value == "BUY"
        deltas = {
            instrument.base_asset_id: base_quantity if buy else -base_quantity,
            instrument.quote_asset_id: -notional if buy else notional,
        }
        deltas[fill.fee.asset_id] = deltas.get(fill.fee.asset_id, Decimal("0")) - max(
            Decimal("0"), fill.fee.amount
        )
        if any(balances.get(asset, Decimal("0")) + delta < 0 for asset, delta in deltas.items()):
            raise ValueError("AQ-LEDGER-NATIVE-FEE-OR-TRADE-BALANCE-INSUFFICIENT")
        if fill.fee.amount != 0:
            for other in self._instrument_by_id.values():
                if (
                    other.instrument_id != instrument.instrument_id
                    and other.base_asset_id == fill.fee.asset_id
                    and self.open_lots(other.instrument_id)
                ):
                    raise ValueError("AQ-LEDGER-THIRD-ASSET-FEE-OPEN-LOT-VALUATION-REQUIRED")
        fee_quantity = (
            max(Decimal("0"), fill.fee.amount) / instrument.contract_multiplier
            if fill.fee.asset_id == instrument.base_asset_id
            else Decimal("0")
        )
        available_lots = sum(
            (lot.remaining_quantity for lot in self.open_lots(instrument.instrument_id)),
            Decimal("0"),
        )
        if available_lots + (fill.quantity.amount if buy else -fill.quantity.amount) < fee_quantity:
            raise ValueError("AQ-LEDGER-NATIVE-BASE-FEE-LOT-INSUFFICIENT")
~~~~

`LedgerEngine._native_spot_fee_lots`，原文件第 420–510 行：


~~~~python
    def _native_spot_fee_lots(
        self,
        fill: Fill,
        instrument: AccountingInstrument,
        drafts: list[_PostingDraft],
        changes: list[LotChange],
    ) -> Decimal:
        """Dispose positive base fees FIFO; base rebates create a lot at the fill mark."""
        if fill.fee.asset_id != instrument.base_asset_id or fill.fee.amount == 0:
            return Decimal("0")
        quantity = abs(fill.fee.amount) / instrument.contract_multiplier
        cost = self._account(
            AccountRole.POSITION_COST, venue=instrument.venue, subject=str(instrument.instrument_id)
        )
        clearing = self._account(
            AccountRole.POSITION_CLEARING,
            venue=instrument.venue,
            subject=str(instrument.instrument_id),
        )
        if fill.fee.amount > 0:
            remaining, _, consumed = self._consume_fifo(
                fill=fill,
                instrument=instrument,
                incoming_side=LotSide.SHORT,
                quantity=quantity,
                drafts=drafts,
            )
            if remaining != 0:
                raise RuntimeError("prechecked native fee lot changed during consumption")
            changes.extend(consumed)
            basis = sum(
                (
                    change.affected_quantity
                    * instrument.contract_multiplier
                    * change.lot_before.entry_price
                    for change in consumed
                    if change.lot_before is not None
                ),
                Decimal("0"),
            )
            self._pair(
                drafts,
                debit=clearing,
                credit=cost,
                amount=basis,
                asset_id=instrument.quote_asset_id,
                memo=f"release FIFO basis of native fee {fill.fill_id}",
            )
            realized = exact_decimal_sum(
                (
                    quantity * instrument.contract_multiplier * fill.price.amount,
                    basis.copy_negate(),
                )
            )
            if realized != 0:
                pnl_account = self._account(
                    AccountRole.TRADING_REALIZED_PNL if realized > 0 else AccountRole.TRADING_LOSS,
                    venue=instrument.venue,
                    subject=str(instrument.quote_asset_id),
                )
                # The asset pays the fee: use memo clearing, never invent quote cash.
                self._pair(
                    drafts,
                    debit=clearing if realized > 0 else pnl_account,
                    credit=pnl_account if realized > 0 else clearing,
                    amount=abs(realized),
                    asset_id=instrument.quote_asset_id,
                    memo=f"FIFO disposal PnL of native fee {fill.fill_id}",
                )
            return realized
        lot = self._new_lot(
            fill=fill, instrument=instrument, side=LotSide.LONG, quantity=quantity, ordinal=1
        )
        self._lots.setdefault(instrument.instrument_id, []).append(lot)
        changes.append(
            LotChange(
                action=LotAction.OPEN,
                lot_after=lot,
                affected_quantity=quantity,
                realized_pnl=Money(amount=Decimal("0"), asset_id=instrument.quote_asset_id),
            )
        )
        self._pair(
            drafts,
            debit=cost,
            credit=clearing,
            amount=quantity * instrument.contract_multiplier * fill.price.amount,
            asset_id=instrument.quote_asset_id,
            memo=f"basis of native fee rebate {fill.fill_id}",
        )
        return Decimal("0")
~~~~

`LedgerEngine._spot_fill`，原文件第 686–864 行：


~~~~python
    def _spot_fill(
        self, fill: Fill, instrument: AccountingInstrument
    ) -> tuple[list[_PostingDraft], list[LotChange], Money]:
        lots = self._lots.get(instrument.instrument_id, ())
        available = sum(
            (lot.remaining_quantity for lot in lots if lot.side is LotSide.LONG), Decimal("0")
        )
        if any(lot.side is LotSide.SHORT for lot in lots) or (
            fill.side.value == "SELL" and fill.quantity.amount > available
        ):
            return self._borrowed_spot_fill(fill, instrument)
        drafts: list[_PostingDraft] = []
        changes: list[LotChange] = []
        quantity = fill.quantity.amount
        venue = instrument.venue
        cash_base = self._account(
            AccountRole.CASH, venue=venue, subject=str(instrument.base_asset_id)
        )
        cash_quote = self._account(
            AccountRole.CASH, venue=venue, subject=str(instrument.quote_asset_id)
        )
        inventory = self._account(
            AccountRole.INVENTORY_CLEARING,
            venue=venue,
            subject=str(instrument.instrument_id),
        )
        cost_account = self._account(
            AccountRole.POSITION_COST,
            venue=venue,
            subject=str(instrument.instrument_id),
        )
        notional = quantity * instrument.contract_multiplier * fill.price.amount
        if fill.side.value == "BUY":
            self._pair(
                drafts,
                debit=cash_base,
                credit=inventory,
                amount=quantity * instrument.contract_multiplier,
                asset_id=instrument.base_asset_id,
                memo=f"spot asset received for {fill.fill_id}",
            )
            self._pair(
                drafts,
                debit=cost_account,
                credit=cash_quote,
                amount=notional,
                asset_id=instrument.quote_asset_id,
                memo=f"spot FIFO basis for {fill.fill_id}",
            )
            lot = self._new_lot(
                fill=fill,
                instrument=instrument,
                side=LotSide.LONG,
                quantity=quantity,
                ordinal=0,
            )
            self._lots.setdefault(instrument.instrument_id, []).append(lot)
            changes.append(
                LotChange(
                    action=LotAction.OPEN,
                    lot_after=lot,
                    affected_quantity=quantity,
                    realized_pnl=Money(
                        amount=Decimal("0"), asset_id=instrument.settlement_asset_id
                    ),
                )
            )
            realized = Money(amount=Decimal("0"), asset_id=instrument.settlement_asset_id)
        else:
            available = sum(
                (
                    lot.remaining_quantity
                    for lot in self._lots.get(instrument.instrument_id, ())
                    if lot.side is LotSide.LONG
                ),
                Decimal("0"),
            )
            if available < quantity:
                raise ValueError("AQ-LEDGER-SPOT-SHORT-REQUIRES-BORROWED-INVENTORY")
            residual, realized_amount, consumed = self._consume_fifo(
                fill=fill,
                instrument=instrument,
                incoming_side=LotSide.SHORT,
                quantity=quantity,
                drafts=drafts,
            )
            if residual != 0:
                raise RuntimeError("prechecked spot inventory changed during FIFO consumption")
            changes.extend(consumed)
            cost_basis = sum(
                (
                    item.affected_quantity
                    * instrument.contract_multiplier
                    * item.lot_before.entry_price
                    for item in consumed
                    if item.lot_before is not None
                ),
                Decimal("0"),
            )
            proceeds = notional
            # Posted proceeds and FIFO basis are the accounting amounts. Recomputing
            # quantity * (exit - entry) can differ in the last Decimal place.
            realized_amount = exact_decimal_sum((proceeds, cost_basis.copy_negate()))
            self._pair(
                drafts,
                debit=inventory,
                credit=cash_base,
                amount=quantity * instrument.contract_multiplier,
                asset_id=instrument.base_asset_id,
                memo=f"spot asset delivered for {fill.fill_id}",
            )
            if realized_amount >= 0:
                drafts.append(
                    _PostingDraft(
                        cash_quote,
                        PostingSide.DEBIT,
                        proceeds,
                        instrument.quote_asset_id,
                        f"spot proceeds for {fill.fill_id}",
                    )
                )
                drafts.append(
                    _PostingDraft(
                        cost_account,
                        PostingSide.CREDIT,
                        cost_basis,
                        instrument.quote_asset_id,
                        f"release spot basis for {fill.fill_id}",
                    )
                )
                if realized_amount > 0:
                    income = self._account(
                        AccountRole.TRADING_REALIZED_PNL,
                        venue=venue,
                        subject=str(instrument.quote_asset_id),
                    )
                    drafts.append(
                        _PostingDraft(
                            income,
                            PostingSide.CREDIT,
                            realized_amount,
                            instrument.quote_asset_id,
                            f"spot realized PnL for {fill.fill_id}",
                        )
                    )
            else:
                loss = self._account(
                    AccountRole.TRADING_LOSS,
                    venue=venue,
                    subject=str(instrument.quote_asset_id),
                )
                drafts.extend(
                    (
                        _PostingDraft(
                            cash_quote,
                            PostingSide.DEBIT,
                            proceeds,
                            instrument.quote_asset_id,
                            f"spot proceeds for {fill.fill_id}",
                        ),
                        _PostingDraft(
                            loss,
                            PostingSide.DEBIT,
                            realized_amount.copy_negate(),
                            instrument.quote_asset_id,
                            f"spot realized loss for {fill.fill_id}",
                        ),
                        _PostingDraft(
                            cost_account,
                            PostingSide.CREDIT,
                            cost_basis,
                            instrument.quote_asset_id,
                            f"release spot basis for {fill.fill_id}",
                        ),
                    )
                )
            realized = Money(amount=realized_amount, asset_id=instrument.settlement_asset_id)
        self._fee_postings(drafts, fill, venue)
        return drafts, changes, realized
~~~~

`LedgerEngine.native_balances`，原文件第 1365–1378 行：


~~~~python
    def native_balances(self) -> tuple[AccountBalance, ...]:
        balances: list[AccountBalance] = []
        for (account_id, asset_id), raw in self._balances.items():
            definition = self.chart.definition(account_id)
            amount = raw if definition.normal_balance is NormalBalance.DEBIT else -raw
            if amount != 0:
                balances.append(
                    AccountBalance(
                        account_id=account_id,
                        asset_id=asset_id,
                        amount=canonical_result(amount),
                    )
                )
        return tuple(sorted(balances, key=lambda item: (str(item.account_id), str(item.asset_id))))
~~~~

### src/aegisquant/research/validation/portfolio_replay.py

来源：[src/aegisquant/research/validation/portfolio_replay.py](https://github.com/tORHANSxd/AegisQuant/blob/main/src/aegisquant/research/validation/portfolio_replay.py)；完整文件 SHA-256：`61c2e4148ff76956997243d4fc34d95369109d2dad621e802bda7f85b217212e`。
依赖导入原文（1–79 行）：


~~~~python
"""Thin, proposal-only shared-capital bridge over the existing ledger and risk modules."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_DOWN, Decimal
from itertools import pairwise
from typing import Any

import numpy as np
from numpy.typing import NDArray
from pydantic import Field, model_validator

from aegisquant.accounting.ledger import LedgerEngine
from aegisquant.accounting.models import (
    AccountingInstrument,
    AccountRole,
    FxRate,
    ValuationQuote,
    ValuationSnapshot,
)
from aegisquant.data.hashing import canonical_sha256
from aegisquant.data.market import InstrumentType
from aegisquant.domain.accounting import LotSide
from aegisquant.domain.base import DomainModel
from aegisquant.domain.execution import OrderSide
from aegisquant.domain.identifiers import (
    AssetId,
    InstrumentId,
    ProposalId,
    RiskDecisionId,
    ValuationSnapshotId,
)
from aegisquant.domain.time import UtcDateTime
from aegisquant.domain.values import (
    NonNegativeDecimal,
    PositiveDecimal,
    UnitInterval,
    canonical_result,
)
from aegisquant.execution.accounts import AccountBalance
from aegisquant.portfolio.models import (
    CovarianceEstimate,
    CovarianceInputContract,
    ExposureConstraint,
    ExposureDimension,
    PortfolioConstructionPolicy,
    PortfolioProposal,
    RiskRegime,
    SignalInput,
)
from aegisquant.portfolio.optimizer import (
    _capacity_weight,  # pyright: ignore[reportPrivateUsage] -- reuse the existing capacity curve.
    _dimension_key,  # pyright: ignore[reportPrivateUsage] -- one definition of group membership.
    _portfolio_variance,  # pyright: ignore[reportPrivateUsage] -- reuse Decimal risk arithmetic.
    build_portfolio_proposal,
    target_quantity_adjustment,
)
from aegisquant.portfolio.risk_estimation import estimate_covariance
from aegisquant.research.validation.evidence_contract import Row, decimal, require, utc
from aegisquant.risk.engine import evaluate_circuit_breakers, evaluate_portfolio_proposal
from aegisquant.risk.models import (
    RiskDecision,
    RiskDecisionStatus,
    RiskEvent,
    RiskSnapshot,
    RiskState,
)
from aegisquant.risk.policy import SignedRiskPolicy, verify_signed_risk_policy
from aegisquant.risk.state_machine import SAFETY_RANK, transition_risk_state
from aegisquant.risk.stress import PortfolioStressScenario, run_portfolio_stress

ZERO, ONE = Decimal("0"), Decimal("1")
FILES = (
    "src/aegisquant/portfolio/risk_estimation.py",
    "src/aegisquant/portfolio/models.py",
~~~~

`account_from_ledger`，原文件第 205–352 行：


~~~~python
def account_from_ledger(
    ledger: LedgerEngine,
    *,
    assets: Sequence[BridgeAsset],
    quote_balance: AccountBalance,
    fx_rates: Mapping[AssetId, FxRate],
    pending: Sequence[PendingReservation],
    unsettled_quote: Decimal,
    decision_time: UtcDateTime,
    balance_available_at: UtcDateTime,
    fx_available_at: UtcDateTime,
) -> BridgeAccount:
    """Read the authoritative ledger; venue available cash is a ceiling, never sale proceeds."""
    at = utc(decision_time)
    require(
        utc(balance_available_at) <= at and utc(fx_available_at) <= at,
        "AQ-BRIDGE-FUTURE-BALANCE-OR-FX",
    )
    ordered = tuple(sorted(assets, key=lambda item: str(item.instrument.instrument_id)))
    require(
        bool(ordered) and len({a.instrument.instrument_id for a in ordered}) == len(ordered),
        "AQ-BRIDGE-ASSET-IDENTITY",
    )
    require(
        len({a.instrument.base_asset_id for a in ordered}) == len(ordered),
        "AQ-BRIDGE-DUPLICATE-BASE-ASSET",
    )
    require(len({a.instrument.venue for a in ordered}) == 1, "AQ-BRIDGE-SINGLE-VENUE-ACCOUNT")
    require(len({a.signal.account_id for a in ordered}) == 1, "AQ-BRIDGE-SINGLE-VENUE-ACCOUNT")
    quote, venue = quote_balance.asset_id, ordered[0].instrument.venue
    require(
        all(a.instrument.quote_asset_id == quote and a.available_at <= at for a in ordered),
        "AQ-BRIDGE-QUOTE-OR-FUTURE-MARK",
    )
    require(
        all(record.journal_entry.recorded_at <= at for record in ledger.records),
        "AQ-BRIDGE-FUTURE-LEDGER-EVENT",
    )
    require(
        ledger.policy.spot_fee_policy == "SPOT_NATIVE_FEES_V2",
        "AQ-BRIDGE-NATIVE-FEE-POLICY-REQUIRED",
    )
    require(unsettled_quote.is_finite() and unsettled_quote >= 0, "AQ-BRIDGE-UNSETTLED-QUOTE")
    by_id = {a.instrument.instrument_id: a for a in ordered}
    native: dict[AssetId, Decimal] = {}
    for balance in ledger.native_balances():
        definition = ledger.chart.definition(balance.account_id)
        if definition.economic_balance:
            require(
                definition.role is AccountRole.CASH and definition.venue == venue,
                "AQ-BRIDGE-UNSUPPORTED-ACCOUNT-OR-LIABILITY",
            )
            native[balance.asset_id] = native.get(balance.asset_id, ZERO) + balance.amount
    require(all(v >= 0 for v in native.values()), "AQ-BRIDGE-NEGATIVE-CASH")
    require(
        native.get(quote, ZERO) == quote_balance.total and unsettled_quote <= quote_balance.total,
        "AQ-BRIDGE-QUOTE-RECONCILIATION",
    )
    quantities = dict.fromkeys(by_id, ZERO)
    for lot in ledger.open_lots():
        require(
            lot.instrument_id in by_id and lot.side is LotSide.LONG,
            "AQ-BRIDGE-UNCOVERED-OR-SHORT-POSITION",
        )
        quantities[lot.instrument_id] += lot.remaining_quantity
    for asset in ordered:
        require(
            native.get(asset.instrument.base_asset_id, ZERO)
            == quantities[asset.instrument.instrument_id],
            "AQ-BRIDGE-BASE-CASH-LOT-MISMATCH",
        )
        rate = fx_rates.get(asset.instrument.base_asset_id)
        require(
            rate is not None
            and rate.rate == asset.mark
            and rate.reporting_asset_id == quote
            and rate.as_of_time <= at,
            "AQ-BRIDGE-MARK-FX-RECONCILIATION",
        )
    quotes = {
        a.instrument.instrument_id: ValuationQuote(
            instrument_id=a.instrument.instrument_id, as_of_time=at, available_time=at, mark=a.mark
        )
        for a in ordered
    }
    if ledger.open_lots():
        valuation = ledger.valuation_snapshot(quotes)
    else:
        identity = canonical_sha256(
            {
                "ledger": ledger.state_digest().state_hash,
                "as_of": at.isoformat(),
                "empty_lots": True,
            }
        )
        valuation = ValuationSnapshot(
            valuation_snapshot_id=ValuationSnapshotId(identity),
            as_of_time=at,
            available_time=at,
            policy_version=ledger.policy.policy_version,
            lots=(),
            content_hash=identity,
        )
    nav = ledger.equity_snapshot(
        valuation=valuation,
        reporting_asset_id=quote,
        fx_rates=fx_rates,
        valuation_basis="SPOT_NATIVE_MTM_V2",
    ).equity
    require(nav > 0, "AQ-BRIDGE-NONPOSITIVE-NAV")
    reservations = tuple(sorted(pending, key=lambda item: item.order_id))
    require(
        len({p.order_id for p in reservations}) == len(reservations), "AQ-BRIDGE-DUPLICATE-PENDING"
    )
    sells: dict[InstrumentId, Decimal] = dict.fromkeys(by_id, ZERO)
    sides: dict[InstrumentId, set[OrderSide]] = {key: set() for key in by_id}
    for item in reservations:
        require(
            item.instrument_id in by_id and item.available_at <= at,
            "AQ-BRIDGE-UNKNOWN-OR-FUTURE-PENDING",
        )
        sides[item.instrument_id].add(item.side)
        if item.side is OrderSide.SELL:
            sells[item.instrument_id] += item.remaining_quantity
    require(
        all(len(value) <= 1 for value in sides.values()),
        "AQ-BRIDGE-OPPOSING-PENDING-REQUIRES-RECONCILIATION",
    )
    require(
        all(sells[key] <= quantities[key] for key in by_id),
        "AQ-BRIDGE-PENDING-SELL-EXCEEDS-INVENTORY",
    )
    reserved = sum((p.quote_reserve for p in reservations), start=ZERO)
    require(reserved + unsettled_quote <= quote_balance.total, "AQ-BRIDGE-PENDING-EXCEEDS-CASH")
    available = min(quote_balance.available, quote_balance.total - unsettled_quote - reserved)
    return BridgeAccount(
        ledger.state_digest().state_hash,
        at,
        nav,
        quote,
        quote_balance.total,
        available,
        reserved,
        unsettled_quote,
        quantities,
        ordered,
        reservations,
    )
~~~~

`plan_shared_capital`，原文件第 427–767 行：


~~~~python
def plan_shared_capital(
    *,
    ledger: LedgerEngine,
    account: BridgeAccount,
    raw_target_weights: Mapping[InstrumentId, Decimal],
    covariance: CovarianceEstimate,
    construction: PortfolioConstructionPolicy,
    risk_snapshot: RiskSnapshot,
    signed_policy: SignedRiskPolicy,
    trusted_public_keys: dict[str, bytes],
    prior_risk_state: RiskState,
    risk_transition_sequence: int,
    events: tuple[RiskEvent, ...] = (),
    tail_evidence_ready: bool = False,
) -> PortfolioBridgePlan:
    """Deterministic funded allocation; returns quantities only and never submits orders."""
    require(
        ledger.state_digest().state_hash == account.ledger_hash,
        "AQ-BRIDGE-LEDGER-CHANGED-RECOMPUTE",
    )
    require(
        type(risk_transition_sequence) is int and risk_transition_sequence >= 1,
        "AQ-BRIDGE-RISK-TRANSITION-SEQUENCE",
    )
    require(
        covariance.evidence is not None and covariance.available_at <= account.decision_time,
        "AQ-BRIDGE-CAUSAL-COVARIANCE-REQUIRED",
    )
    if covariance.evidence is not None:
        require(
            covariance.evidence.contract.annualization_days == Decimal("365.25")
            and covariance.evidence.contract.complete_calendar_observations >= 90,
            "AQ-BRIDGE-COVARIANCE-UNIT-OR-COVERAGE",
        )
    require(
        risk_snapshot.ledger_reconciled and risk_snapshot.as_of_time == account.decision_time,
        "AQ-BRIDGE-RISK-SNAPSHOT-RECONCILIATION",
    )
    assets = account.assets
    ids = tuple(a.instrument.instrument_id for a in assets)
    current = {
        a.instrument.instrument_id: canonical_result(
            account.current_quantities[a.instrument.instrument_id] * a.mark / account.nav
        )
        for a in assets
    }
    positions = {p.instrument_id: p.signed_weight for p in risk_snapshot.positions}
    require(
        set(positions) <= set(ids) and all(positions.get(key, ZERO) == current[key] for key in ids),
        "AQ-BRIDGE-RISK-POSITION-MISMATCH",
    )
    signals = tuple(
        a.signal.model_copy(
            update={"current_weight": current[a.instrument.instrument_id], "expected_return": ZERO}
        )
        for a in assets
    )
    policy = verify_signed_risk_policy(
        signed_policy,
        trusted_public_keys=trusted_public_keys,
        decision_time=account.decision_time,
        deployment_stage=construction.environment_stage,
    )
    # Enforce the stricter signed limits also on pending and intermediate fill order.
    constraints = {(c.dimension, c.key): c for c in construction.exposure_constraints}
    limits = policy.pre_trade_limits
    for dimension, keys, maximum in (
        (
            ExposureDimension.ASSET,
            {str(a.signal.asset_id) for a in assets},
            limits.maximum_asset_gross_weight,
        ),
        (
            ExposureDimension.STRATEGY,
            {str(a.signal.strategy_id) for a in assets},
            limits.maximum_strategy_gross_weight,
        ),
    ):
        for key in keys:
            previous = constraints.get((dimension, key))
            constraints[(dimension, key)] = ExposureConstraint(
                dimension=dimension,
                key=key,
                maximum_absolute_weight=min(maximum, previous.maximum_absolute_weight)
                if previous
                else maximum,
            )
    construction = construction.model_copy(
        update={
            "maximum_gross_weight": min(
                construction.maximum_gross_weight, limits.maximum_account_gross_weight, ONE
            ),
            "exposure_constraints": tuple(
                constraints[key]
                for key in sorted(constraints, key=lambda key: (key[0].value, key[1]))
            ),
        }
    )
    circuit = evaluate_circuit_breakers(
        snapshot=risk_snapshot, policy=policy, decision_time=account.decision_time, events=events
    )
    current_risk = risk_metrics(current, assets=assets, covariance=covariance, policy=construction)
    triggered = max(
        circuit.state,
        RiskState.REDUCE_ONLY if current_risk["breaches"] else RiskState.NORMAL,
        key=SAFETY_RANK.__getitem__,
    )
    transition = None
    if prior_risk_state is RiskState.RECOVERY:
        effective_state = RiskState.HALTED if triggered is RiskState.HALTED else RiskState.RECOVERY
    else:
        effective_state = max(prior_risk_state, triggered, key=SAFETY_RANK.__getitem__)
        if effective_state is not prior_risk_state:
            transition = transition_risk_state(
                sequence=risk_transition_sequence,
                current=prior_risk_state,
                target=effective_state,
                automatic=True,
                actor="independent-risk-engine",
                reason_code="AQ-BRIDGE-HARD-RISK",
                occurred_at=account.decision_time,
            )
    hard = effective_state in {RiskState.REDUCE_ONLY, RiskState.HALTED}
    targets = dict.fromkeys(ids, ZERO) if hard else dict(raw_target_weights)
    require(set(raw_target_weights) == set(ids), "AQ-BRIDGE-RAW-TARGET-COVERAGE")
    proposal = build_portfolio_proposal(
        proposal_id=ProposalId(
            canonical_sha256(
                {
                    "ledger": account.ledger_hash,
                    "targets": {str(k): str(v) for k, v in targets.items()},
                    "as_of": account.decision_time.isoformat(),
                }
            )
        ),
        signals=signals,
        covariance=covariance,
        policy=construction,
        portfolio_nav=account.nav,
        as_of_time=account.decision_time,
        created_at=account.decision_time,
        raw_target_weights=targets,
        hard_risk_reduction=hard,
    )
    decision = evaluate_portfolio_proposal(
        proposal=proposal,
        snapshot=risk_snapshot,
        signed_policy=signed_policy,
        trusted_public_keys=trusted_public_keys,
        decision_time=account.decision_time,
        events=events,
    )
    if effective_state is not RiskState.NORMAL:
        reduced = tuple(
            t for t in decision.approved_targets if 0 <= t.approved_target_weight < t.current_weight
        )
        decision = RiskDecision.model_validate(
            {
                **dict(decision),
                "risk_decision_id": RiskDecisionId(
                    canonical_sha256(
                        {
                            "source": str(decision.risk_decision_id),
                            "latched_state": effective_state.value,
                        }
                    )
                ),
                "state": effective_state,
                "new_risk_allowed": False,
                "status": RiskDecisionStatus.REDUCE_ONLY
                if effective_state is RiskState.REDUCE_ONLY
                else RiskDecisionStatus.HALTED
                if effective_state is RiskState.HALTED
                else RiskDecisionStatus.REJECTED,
                "approved_targets": reduced if effective_state is RiskState.REDUCE_ONLY else (),
                "reason_codes": (*decision.reason_codes, "AQ-BRIDGE-PERSISTED-RISK-STATE"),
            }
        )
    approved = {t.instrument_id: t.approved_target_weight for t in decision.approved_targets}
    pending_net = dict.fromkeys(ids, ZERO)
    pending_buy = dict.fromkeys(ids, ZERO)
    pending_sell = dict.fromkeys(ids, ZERO)
    for item in account.pending:
        direction = ONE if item.side is OrderSide.BUY else -ONE
        pending_net[item.instrument_id] += direction * item.remaining_quantity
        (pending_buy if item.side is OrderSide.BUY else pending_sell)[item.instrument_id] += (
            item.remaining_quantity
        )
    candidates: dict[InstrumentId, Decimal] = dict.fromkeys(ids, ZERO)
    cancels: list[str] = [
        p.order_id
        for p in account.pending
        if p.side is OrderSide.BUY
        and (hard or not decision.new_risk_allowed or not tail_evidence_ready)
    ]
    blocked: list[str] = (
        ["RISK_STATE_BLOCKED"] if effective_state in {RiskState.CAUTION, RiskState.RECOVERY} else []
    )
    for asset, signal in zip(assets, signals, strict=True):
        key = asset.instrument.instrument_id
        if key not in approved:
            continue
        adjustment = target_quantity_adjustment(
            target_quantity=approved[key] * account.nav / asset.mark,
            current_quantity=account.current_quantities[key],
            signed_pending_quantity=pending_net[key],
            price=asset.mark,
            quantity_step=asset.quantity_step,
            minimum_notional=asset.minimum_notional,
        )
        if adjustment.cancel_pending_first:
            cancels.extend(p.order_id for p in account.pending if p.instrument_id == key)
            continue
        quantity = adjustment.signed_order_quantity
        capacity_qty = (
            _capacity_weight(signal, nav=account.nav, policy=construction)
            * account.nav
            / asset.mark
        )
        capacity_qty = (capacity_qty / asset.quantity_step).to_integral_value(
            rounding=ROUND_DOWN
        ) * asset.quantity_step
        quantity = min(abs(quantity), capacity_qty) * (ONE if quantity >= 0 else -ONE)
        if quantity < 0:
            quantity = -min(abs(quantity), account.current_quantities[key] - pending_sell[key])
        if quantity > 0 and (hard or not decision.new_risk_allowed or not tail_evidence_ready):
            quantity = ZERO
            blocked.append("NEW_RISK_NOT_ADMITTED")
        candidates[key] = quantity
    required = sum(
        (
            max(ZERO, candidates[a.instrument.instrument_id])
            * a.mark
            * (1 + a.maximum_execution_cost_fraction)
            for a in assets
        ),
        start=ZERO,
    )
    scale = min(ONE, account.quote_available / required) if required else ONE
    for asset in assets:
        key = asset.instrument.instrument_id
        if candidates[key] > 0:
            candidates[key] = (candidates[key] * scale / asset.quantity_step).to_integral_value(
                rounding=ROUND_DOWN
            ) * asset.quantity_step
        if abs(candidates[key]) * asset.mark < asset.minimum_notional:
            candidates[key] = ZERO

    def post_risk(quantities: Mapping[InstrumentId, Decimal], worst_prefix: bool) -> dict[str, Any]:
        maximum_costs = sum(
            (
                p.remaining_quantity * p.maximum_price * p.maximum_cost_fraction
                for p in account.pending
            ),
            start=ZERO,
        )
        maximum_costs += sum(
            (
                abs(quantities[a.instrument.instrument_id])
                * a.mark
                * a.maximum_execution_cost_fraction
                for a in assets
            ),
            start=ZERO,
        )
        post_nav = account.nav - maximum_costs
        require(post_nav > 0, "AQ-BRIDGE-COSTS-EXHAUST-NAV")
        weights = {
            a.instrument.instrument_id: canonical_result(
                (
                    account.current_quantities[a.instrument.instrument_id]
                    + pending_buy[a.instrument.instrument_id]
                    + (
                        max(ZERO, quantities[a.instrument.instrument_id])
                        if worst_prefix
                        else quantities[a.instrument.instrument_id]
                        - pending_sell[a.instrument.instrument_id]
                    )
                )
                * a.mark
                / post_nav
            )
            for a in assets
        }
        return risk_metrics(weights, assets=assets, covariance=covariance, policy=construction)

    worst, post = post_risk(candidates, True), post_risk(candidates, False)
    if worst["breaches"] or post["breaches"]:
        # Unfilled sales never finance or offset the risk of buys. Retain executable hard exits.
        candidates = {key: min(ZERO, value) if hard else ZERO for key, value in candidates.items()}
        blocked.append("POST_ROUNDING_RISK")
        worst, post = post_risk(candidates, True), post_risk(candidates, False)
    required = sum(
        (
            max(ZERO, candidates[a.instrument.instrument_id])
            * a.mark
            * (1 + a.maximum_execution_cost_fraction)
            for a in assets
        ),
        start=ZERO,
    )
    require(required <= account.quote_available, "AQ-BRIDGE-CASH-POSTCONDITION")
    unresolved = bool(
        current_risk["breaches"]
        or worst["breaches"]
        or post["breaches"]
        or any("UNRESOLVED-BREACH" in reason for reason in proposal.constraint_summary)
    )
    status = (
        "BREACH_UNEXECUTABLE_OR_PENDING"
        if hard or unresolved
        else "CANCEL_PENDING_FIRST"
        if cancels
        else "BLOCKED"
        if blocked
        else "PROPOSAL_ONLY"
    )
    return PortfolioBridgePlan(
        proposal,
        decision,
        candidates,
        required,
        tuple(sorted(set(cancels))),
        status,
        {
            "current_risk": current_risk,
            "worst_fill_order_risk": worst,
            "post_rounding_risk": post,
            "pending_quote_reserved": str(account.pending_quote_reserved),
            "unsettled_quote": str(account.unsettled_quote),
            "quote_available": str(account.quote_available),
            "blocked": sorted(set(blocked)),
            "assumed_sale_proceeds": "0",
            "submitted_orders": 0,
            "tail_evidence_ready": tail_evidence_ready,
            "partial_fill_requires_fresh_ledger_and_risk_snapshot": True,
            "effective_risk_state": effective_state.value,
            "risk_transition": transition.model_dump(mode="json") if transition else None,
            "automatic_recovery_allowed": False,
        },
    )
~~~~

### src/aegisquant/research/datasets/pit_universe.py

来源：[src/aegisquant/research/datasets/pit_universe.py](https://github.com/tORHANSxd/AegisQuant/blob/main/src/aegisquant/research/datasets/pit_universe.py)；完整文件 SHA-256：`23e15f66924323e5112dfd6b381d74fa5d75f77b97edbf247e62bc9f19eaefca`。
`audit_universe_at`，原文件第 229–426 行：


~~~~python
def audit_universe_at(
    universe: PointInTimeUniverse,
    observations: Iterable[LiquidityObservation],
    *,
    rules: Iterable[RuleProvenance],
    decision_time: UtcDateTime,
    minimum_quote_volume: Decimal,
    warmup_requirements: Mapping[str, int],
    minimum_history_bars: int = 240,
    maximum_age: timedelta = timedelta(hours=4),
    held_instrument_ids: Iterable[str] = (),
    allow_synthetic: bool = False,
) -> PITUniverseSnapshot:
    """Strict B2 decision view; no market loader, account mutation, order or PnL interface."""
    if (
        not minimum_quote_volume.is_finite()
        or minimum_quote_volume <= 0
        or minimum_history_bars < 1
        or maximum_age <= timedelta(0)
        or not warmup_requirements
        or any(type(value) is not int or value < 1 for value in warmup_requirements.values())
    ):
        raise ValueError("AQ-PIT-UNREGISTERED-ELIGIBILITY-LIMITS")
    required = max(minimum_history_bars, *warmup_requirements.values())
    known = universe.known_events(as_of_time=decision_time)
    current = {
        row.instrument_id: row for row in universe.current_memberships(as_of_time=decision_time)
    }
    identities: set[tuple[str, str]] = set()
    for member in current.values():
        if (
            member.eligible
            and member.evidence is not None
            and (member.effective_to is None or decision_time < member.effective_to)
        ):
            identity = member.evidence.venue, member.evidence.symbol
            if identity in identities:
                raise ValueError("AQ-PIT-OVERLAPPING-SYMBOL-INCARNATIONS")
            identities.add(identity)
    liquidity = _latest_liquidity(observations, decision_time)
    rule_view = _known_rules(rules, decision_time)
    held = tuple(sorted(set(held_instrument_ids)))
    decisions: list[UniverseDecision] = []
    for instrument in sorted({row.instrument_id for row in known} | set(held)):
        member = current.get(instrument)
        base = UniverseDecision(
            instrument_uid=instrument,
            membership_id=member.membership_id if member else None,
            disposition="UNKNOWN",
            reason_codes=(),
            required_history_bars=required,
        )
        if member is None:
            reason = (
                "NOT_YET_EFFECTIVE"
                if any(row.instrument_id == instrument for row in known)
                else "MEMBERSHIP_NOT_KNOWN"
            )
            decisions.append(
                base.model_copy(
                    update={
                        "disposition": "EXCLUDED" if reason == "NOT_YET_EFFECTIVE" else "UNKNOWN",
                        "reason_codes": (reason,),
                    }
                )
            )
            continue
        if not member.eligible or (
            member.effective_to is not None and decision_time >= member.effective_to
        ):
            decisions.append(
                base.model_copy(
                    update={"disposition": "EXCLUDED", "reason_codes": ("MEMBERSHIP_NOT_TRADABLE",)}
                )
            )
            continue
        reasons: list[str] = []
        unknown = False
        proof = member.evidence
        if (
            proof is None
            or proof.availability_evidence_kind == "UNKNOWN"
            or (proof.availability_evidence_kind == "SYNTHETIC" and not allow_synthetic)
        ):
            reasons.append("MEMBERSHIP_EVIDENCE_UNVERIFIED")
            unknown = True
        row = liquidity.get(instrument)
        if row is None:
            reasons.append("LIQUIDITY_NOT_KNOWN")
            unknown = True
        else:
            base = base.model_copy(
                update={
                    "liquidity_source_sha256": row.source_sha256,
                    "trailing_quote_volume": row.trailing_quote_volume,
                }
            )
            if decision_time - row.window_end > maximum_age:
                reasons.append("LIQUIDITY_STALE")
            if row.trailing_quote_volume <= 0 or row.trailing_quote_volume < minimum_quote_volume:
                reasons.append("LIQUIDITY_BELOW_THRESHOLD")
            detail = row.evidence
            if detail is None:
                reasons.append("LIQUIDITY_DETAIL_NOT_RECEIVED")
                unknown = True
            else:
                if detail.quote_method not in {
                    "EXCHANGE_QUOTE_TURNOVER",
                    "TRADE_QUOTE_SUM",
                } and not (allow_synthetic and detail.quote_method == "SYNTHETIC"):
                    reasons.append("QUOTE_TURNOVER_NOT_EXACT")
                    unknown = True
                ordered = sorted(detail.bars, key=lambda bar: bar.close_time)
                consecutive = int(bool(ordered) and ordered[-1].close_time == row.window_end)
                for newer, older in pairwise(reversed(ordered)):
                    if not consecutive or newer.close_time - older.close_time != timedelta(hours=4):
                        break
                    consecutive += 1
                window_count = sum(
                    row.window_start < bar.close_time <= row.window_end for bar in ordered
                )
                lifecycle_bars = (
                    sum(bar.close_time > member.effective_from for bar in ordered[-consecutive:])
                    if consecutive
                    else 0
                )
                base = base.model_copy(
                    update={
                        "liquidity_detail_sha256": detail.detail_sha256,
                        "contiguous_4h_bars": consecutive,
                        "liquidity_window_bars": window_count,
                        "tradable_history_4h_bars": lifecycle_bars,
                        "liquidity_gap_count": 180 - window_count,
                    }
                )
                if row.complete_history_4h_bars != consecutive:
                    raise ValueError("AQ-PIT-CONTIGUOUS-HISTORY-COUNT-MISMATCH")
                if window_count != 180:
                    reasons.append("LIQUIDITY_WINDOW_GAP")
                    unknown = True
                if min(consecutive, lifecycle_bars) < required:
                    reasons.append("CONTIGUOUS_WARMUP_INCOMPLETE")
        active_rules = rule_view.get(instrument, [])
        if len(active_rules) > 1:
            raise ValueError("AQ-PIT-AMBIGUOUS-ACTIVE-RULE")
        if not active_rules:
            reasons.append("RULES_NOT_KNOWN")
            unknown = True
        else:
            rule = active_rules[0]
            base = base.model_copy(update={"rule_payload_sha256": rule.payload_sha256})
            selected = HistoricalRuleBook((rule.rule,)).at(
                venue_id=rule.rule.venue_id,
                instrument_id=rule.rule.instrument_id,
                event_time=decision_time,
            )
            if proof is not None and str(selected.venue_id) != proof.venue:
                raise ValueError("AQ-PIT-RULE-VENUE-IDENTITY")
            if rule.verified_kind != "ARCHIVED_EXCHANGE_RULE" and not (
                allow_synthetic and rule.verified_kind == "SYNTHETIC"
            ):
                reasons.append("RULES_UNVERIFIED")
                unknown = True
            if not selected.trading_enabled:
                reasons.append("RULES_TRADING_DISABLED")
        decisions.append(
            base.model_copy(
                update={
                    "reason_codes": tuple(reasons),
                    "disposition": "UNKNOWN" if unknown else "EXCLUDED" if reasons else "ELIGIBLE",
                }
            )
        )
    membership_snapshot = universe.snapshot(as_of_time=decision_time)
    policy_hash = canonical_sha256(
        {
            "minimum_quote_volume": str(minimum_quote_volume),
            "warmup_requirements": dict(warmup_requirements),
            "minimum_history_bars": minimum_history_bars,
            "maximum_age_seconds": str(maximum_age.total_seconds()),
            "allow_synthetic": allow_synthetic,
        }
    )
    provisional = PITUniverseSnapshot(
        snapshot_sha256="",
        membership_snapshot=membership_snapshot,
        eligible_instrument_ids=tuple(
            row.instrument_uid for row in decisions if row.disposition == "ELIGIBLE"
        ),
        decisions=tuple(decisions),
        known_future_event_ids=tuple(
            sorted(row.membership_id for row in known if row.effective_from > decision_time)
        ),
        held_instrument_ids=held,
        policy_sha256=policy_hash,
    )
    digest = canonical_sha256(provisional.model_dump(mode="json", exclude={"snapshot_sha256"}))
    return provisional.model_copy(update={"snapshot_sha256": digest})
~~~~

### src/aegisquant/research/validation/splits.py

来源：[src/aegisquant/research/validation/splits.py](https://github.com/tORHANSxd/AegisQuant/blob/main/src/aegisquant/research/validation/splits.py)；完整文件 SHA-256：`6cd46de145afac6ea774489cb4ea40de82c31a68e1cca0fcf95df1b4cd83a066`。
`SampleSpan`，原文件第 25–53 行：


~~~~python
class SampleSpan(DomainModel):
    sample_id: str
    group_time: UtcDateTime
    label_start_time: UtcDateTime
    label_end_time: UtcDateTime
    regime: str | None = None
    feature_dependency_start: UtcDateTime | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    label_available_time: UtcDateTime | None = Field(default=None, exclude_if=lambda v: v is None)
    episode_id: str | None = Field(default=None, exclude_if=lambda v: v is None)

    @model_validator(mode="after")
    def validate_span(self) -> SampleSpan:
        if not self.group_time < self.label_start_time <= self.label_end_time:
            raise ValueError("sample label window must be strictly future")
        if (
            self.feature_dependency_start is not None
            and self.feature_dependency_start > self.group_time
        ):
            raise ValueError("feature dependency cannot begin after decision")
        if (
            self.label_available_time is not None
            and self.label_available_time < self.label_end_time
        ):
            raise ValueError("label cannot be available before its end")
        if self.episode_id is not None and not self.episode_id.strip():
            raise ValueError("episode identity cannot be blank")
        return self
~~~~

`dependency_interval`，原文件第 56–65 行：


~~~~python
def dependency_interval(sample: SampleSpan) -> tuple[UtcDateTime, UtcDateTime]:
    if (
        sample.feature_dependency_start is None
        or sample.label_available_time is None
        or sample.episode_id is None
    ):
        raise ValueError(
            "strict interval purge requires feature, availability and episode metadata"
        )
    return sample.feature_dependency_start, sample.label_available_time
~~~~

`purge_interval_partitions`，原文件第 68–126 行：


~~~~python
def purge_interval_partitions(
    partitions: tuple[tuple[SampleSpan, ...], ...],
    *,
    ends: tuple[UtcDateTime, ...],
    information_embargo: timedelta = timedelta(0),
) -> tuple[tuple[tuple[SampleSpan, ...], ...], tuple[str, ...]]:
    """Keep later partitions; remove whole earlier time/episode groups on any overlap.

    Closed dependency intervals include label publication lag. Calendar ends are
    exclusive. This conservative purge includes feature lookback, not only labels.
    """
    if len(partitions) != len(ends) or information_embargo < timedelta(0):
        raise ValueError("invalid partition ends or information embargo")
    values = tuple(item for partition in partitions for item in partition)
    if len({item.sample_id for item in values}) != len(values):
        raise ValueError("duplicate sample across partitions")
    time_partition: dict[UtcDateTime, int] = {}
    for index, partition in enumerate(partitions):
        for item in partition:
            dependency_interval(item)
            if item.group_time >= ends[index] or (index and item.group_time < ends[index - 1]):
                raise ValueError("sample decision outside ordered partition")
            if time_partition.setdefault(item.group_time, index) != index:
                raise ValueError("all assets at the same time must stay grouped")
    if any(a >= b for a, b in pairwise(ends)):
        raise ValueError("partition ends must increase")
    kept: list[tuple[SampleSpan, ...]] = []
    removed: set[str] = set()
    for index, partition in enumerate(partitions):
        future = tuple(item for later in partitions[index + 1 :] for item in later)
        bad = {
            item.sample_id
            for item in partition
            if dependency_interval(item)[1] + information_embargo >= ends[index]
            or any(
                item.episode_id == other.episode_id
                or (
                    dependency_interval(item)[0] <= dependency_interval(other)[1]
                    and dependency_interval(item)[1] + information_embargo
                    >= dependency_interval(other)[0]
                )
                for other in future
            )
        }
        # ponytail: quadratic closure is fine for episode ledgers; index intervals if volume warrants it.
        while True:
            times = {item.group_time for item in partition if item.sample_id in bad}
            episodes = {item.episode_id for item in partition if item.sample_id in bad}
            expanded = {
                item.sample_id
                for item in partition
                if item.group_time in times or item.episode_id in episodes
            }
            if expanded == bad:
                break
            bad = expanded
        removed.update(bad)
        kept.append(tuple(item for item in partition if item.sample_id not in bad))
    return tuple(kept), tuple(sorted(removed))
~~~~

### src/aegisquant/research/validation/ml_contract.py

来源：[src/aegisquant/research/validation/ml_contract.py](https://github.com/tORHANSxd/AegisQuant/blob/main/src/aegisquant/research/validation/ml_contract.py)；完整文件 SHA-256：`e40055462e924024ff301d708054284ad5152020572e80333f6d12e2eac22a55`。
`validate_registered_fit`，原文件第 200–225 行：


~~~~python
def validate_registered_fit(
    fit: FitProvenance, registrations: tuple[FoldRegistration, ...]
) -> FoldRegistration:
    if (
        not registrations
        or len({item.fold_id for item in registrations}) != len(registrations)
        or len({item.generation for item in registrations}) != 1
    ):
        raise ValueError("current experiment must have one generation and unique registered folds")
    matching = tuple(item for item in registrations if item.fold_id == fit.fold_id)
    if len(matching) != 1:
        raise ValueError("fit fold is absent from the current registration")
    registered = matching[0]
    FoldRegistration.model_validate(dict(registered))
    if (
        fit.split_manifest_sha256 != registered.manifest_sha256
        or fit.label_contract_sha256 != registered.label_contract_sha256
        or fit.scope != registered.scope
        or fit.training_spans != registered.training_spans
        or fit.model_specification_sha256 != registered.model_specification_sha256
        or fit.information_embargo_seconds != registered.information_embargo_seconds
        or {item.name: item.specification_sha256 for item in fit.transforms}
        != registered.transform_specification_hashes
    ):
        raise ValueError("fit provenance does not bind the current registered fold content")
    return registered
~~~~

`validate_oof_alignment`，原文件第 228–257 行：


~~~~python
def validate_oof_alignment(
    records: tuple[OOFPrediction, ...],
    *,
    sample_ids: tuple[str, ...],
    timestamps: tuple[datetime, ...],
    label_end_times: tuple[datetime, ...],
    consumed_at: datetime,
    registrations: tuple[FoldRegistration, ...],
) -> str:
    if (
        not records
        or len(set(sample_ids)) != len(sample_ids)
        or tuple(item.sample.sample_id for item in records) != sample_ids
        or len(records) != len(timestamps)
        or len(records) != len(label_end_times)
    ):
        raise ValueError("OOF predictions must align exactly with all calibration identities")
    for item, time, end in zip(records, timestamps, label_end_times, strict=True):
        # Revalidate copied/deserialized models at the fit trust boundary.
        OOFPrediction.model_validate(dict(item))
        registered = validate_registered_fit(item.fit, registrations)
        if item.sample not in registered.evaluation_spans:
            raise ValueError("OOF sample is absent from its registered evaluation partition")
        if (
            item.sample.group_time != time
            or item.sample.label_end_time != end
            or dependency_interval(item.sample)[1] >= consumed_at
        ):
            raise ValueError("OOF calibration labels/timestamps are unavailable or misaligned")
    return canonical_sha256([item.model_dump(mode="json") for item in records])
~~~~

### src/aegisquant/labels/episodes.py

来源：[src/aegisquant/labels/episodes.py](https://github.com/tORHANSxd/AegisQuant/blob/main/src/aegisquant/labels/episodes.py)；完整文件 SHA-256：`715722f35412bee7c7b11014e7fb3d95059b63b525a6d01c97ea21ab4e29e9b4`。
`label_base_opportunities`，原文件第 59–129 行：


~~~~python
def label_base_opportunities(
    *,
    opportunities: tuple[BaseOpportunity, ...],
    expected_opportunity_ids: tuple[str, ...],
    opportunity_set_sha256: str,
    observations: dict[str, tuple[PricePathObservation, ...]],
    costs: dict[str, CostAssumption],
    observed_through: UtcDateTime,
) -> tuple[EpisodeLabel, ...]:
    """The caller supplies a frozen complete opportunity ledger, including ML rejects.

    The hash binds the supplied ID set; it is not proof of empirical completeness.
    Counterfactual executable paths reuse the existing t+1, two-leg cost generator.
    """
    ids = tuple(item.opportunity_id for item in opportunities)
    if (
        len(ids) != len(set(ids))
        or len(expected_opportunity_ids) != len(set(expected_opportunity_ids))
        or set(ids) != set(expected_opportunity_ids)
    ):
        raise ValueError("must label the complete unfiltered opportunity set")
    if opportunity_set_sha256 != canonical_sha256(sorted(expected_opportunity_ids)):
        raise ValueError("frozen opportunity identity hash mismatch")
    output: list[EpisodeLabel] = []
    for item in sorted(opportunities, key=lambda x: (x.decision_time, x.opportunity_id)):
        path = observations[item.instrument_id]
        if (
            item.exit_index >= len(path)
            or path[item.decision_index].available_time != item.decision_time
        ):
            raise ValueError("opportunity path/decision identity mismatch")
        if any(
            p.instrument_id != item.instrument_id
            for p in path[item.decision_index : item.exit_index + 1]
        ):
            raise ValueError("opportunity path instrument mismatch")
        if item.exit_reason_available_time >= path[item.exit_index].event_time:
            raise ValueError("exit cannot precede the causal exit reason")
        available = max(
            item.exit_reason_available_time,
            *(p.available_time for p in path[item.decision_index + 1 : item.exit_index + 1]),
        )
        if available > observed_through:
            raise ValueError("episode label has not matured")
        label = generate_return_path_label(
            observations=path,
            decision_index=item.decision_index,
            horizon_steps=item.exit_index - item.decision_index,
            cost=costs[item.opportunity_id],
            risk_flat_threshold=Decimal(0),
        )
        output.append(
            EpisodeLabel(
                opportunity=item,
                span=SampleSpan(
                    sample_id=item.opportunity_id,
                    group_time=item.decision_time,
                    label_start_time=label.label_start_time,
                    label_end_time=label.label_end_time,
                    feature_dependency_start=item.feature_dependency_start,
                    label_available_time=available,
                    episode_id=item.episode_id,
                ),
                return_path=label,
                worth_accepting=label.net_return > 0,
                capital_seconds=item.capital_committed
                * Decimal(str((label.label_end_time - label.label_start_time).total_seconds())),
                opportunity_set_sha256=opportunity_set_sha256,
            )
        )
    return tuple(output)
~~~~

### src/aegisquant/research/validation/paired_bootstrap.py

来源：[src/aegisquant/research/validation/paired_bootstrap.py](https://github.com/tORHANSxd/AegisQuant/blob/main/src/aegisquant/research/validation/paired_bootstrap.py)；完整文件 SHA-256：`87c8e6472552b0f00f7042c2ece5dd713464d6c94924d014d1a3f92d890bb9ba`。
以下为当前完整文件（1–173 行）。


~~~~python
"""Paired circular block inference on a common fixed-frequency return clock."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]
LOG_GROWTH_ESTIMAND = "MEAN_LOG_NET_RETURN_DIFFERENCE_PER_OBSERVATION_V1"


@dataclass(frozen=True)
class PairedBootstrap:
    compound_returns: FloatArray
    mean_returns: FloatArray
    observed_compound_returns: FloatArray
    observed_mean_returns: FloatArray
    reality_check_p_value: float
    repetitions: int
    block_bars: int

    @property
    def estimand_ids(self) -> dict[str, str]:
        """Sidecar identity; legacy serialized fields and difference keys stay intact."""
        return {
            "ci95": "TERMINAL_COMPOUND_NET_RETURN_DIFFERENCE_V1",
            "one_sided_mean_p_value": "MEAN_SIMPLE_NET_RETURN_DIFFERENCE_PER_OBSERVATION_V1",
        }

    def difference(self, candidate: int, baseline: int) -> dict[str, float]:
        delta = self.compound_returns[:, candidate] - self.compound_returns[:, baseline]
        low, high = np.quantile(delta, (0.025, 0.975))
        observed_mean = float(
            self.observed_mean_returns[candidate] - self.observed_mean_returns[baseline]
        )
        centered = self.mean_returns[:, candidate] - self.mean_returns[:, baseline] - observed_mean
        return {
            "observed_compound_return_difference": float(
                self.observed_compound_returns[candidate] - self.observed_compound_returns[baseline]
            ),
            "ci95_lower": float(low),
            "ci95_upper": float(high),
            "one_sided_mean_p_value": float(
                (np.sum(centered >= observed_mean) + 1) / (len(delta) + 1)
            ),
        }


def _validate_returns(values: FloatArray, repetitions: int, block_bars: int) -> None:
    if values.ndim != 2 or not np.all(np.isfinite(values)) or np.any(values <= -1):
        raise ValueError("bootstrap requires finite aligned strategy return columns above -100%")
    count, strategies = values.shape
    if count < block_bars * 4 or block_bars < 1 or repetitions < 100 or strategies < 1:
        raise ValueError("insufficient bootstrap observations or repetitions")


def _circular_block_totals(
    values: FloatArray, *, repetitions: int, block_bars: int, seed: int
) -> FloatArray:
    """One shared row-index draw for every column; never draw assets independently."""
    count, strategies = values.shape
    full_blocks, remainder = divmod(count, block_bars)
    starts_per_draw = full_blocks + bool(remainder)
    # Prefix sums avoid allocating repetitions x bars x strategies arrays.
    doubled = np.concatenate((values, values[:block_bars]), axis=0)
    prefix = np.concatenate((np.zeros((1, strategies)), np.cumsum(doubled, axis=0)))
    block_sum = prefix[block_bars : count + block_bars] - prefix[:count]
    rng = np.random.default_rng(seed)
    sampled = np.empty((repetitions, strategies))
    for begin in range(0, repetitions, 128):
        end = min(repetitions, begin + 128)
        starts = rng.integers(0, count, size=(end - begin, starts_per_draw))
        totals = np.sum(block_sum[starts[:, :full_blocks]], axis=1)
        if remainder:
            last = starts[:, -1]
            totals += prefix[last + remainder] - prefix[last]
        sampled[begin:end] = totals
    return sampled


def paired_block_bootstrap(
    values: FloatArray,
    *,
    repetitions: int = 10000,
    block_bars: int = 6,
    seed: int = 20260903,
) -> PairedBootstrap:
    _validate_returns(values, repetitions, block_bars)
    count = len(values)
    means = (
        _circular_block_totals(values, repetitions=repetitions, block_bars=block_bars, seed=seed)
        / count
    )
    compounded = np.expm1(
        _circular_block_totals(
            np.log1p(values), repetitions=repetitions, block_bars=block_bars, seed=seed
        )
    )
    observed_means = np.mean(values, axis=0)
    max_null = np.max(means - observed_means, axis=1)
    reality_p = (int(np.sum(max_null >= max(0.0, float(np.max(observed_means))))) + 1) / (
        repetitions + 1
    )
    if not math.isfinite(reality_p) or not np.all(np.isfinite(compounded)):
        raise ValueError("bootstrap produced non-finite statistics")
    return PairedBootstrap(
        compounded,
        means,
        np.expm1(np.sum(np.log1p(values), axis=0)),
        observed_means,
        reality_p,
        repetitions,
        block_bars,
    )


@dataclass(frozen=True)
class PairedLogGrowth:
    """CI and centered one-sided test for the same mean log-growth difference."""

    mean_log_returns: FloatArray
    observed_mean_log_returns: FloatArray
    repetitions: int
    block_bars: int
    estimand_id: str = LOG_GROWTH_ESTIMAND

    def difference(self, candidate: int, baseline: int) -> dict[str, float | str]:
        delta = self.mean_log_returns[:, candidate] - self.mean_log_returns[:, baseline]
        observed = float(
            self.observed_mean_log_returns[candidate] - self.observed_mean_log_returns[baseline]
        )
        low, high = np.quantile(delta, (0.025, 0.975))
        return {
            "estimand_id": self.estimand_id,
            "observed_mean_log_return_difference": observed,
            "ci95_lower": float(low),
            "ci95_upper": float(high),
            "one_sided_p_value": float(
                (np.sum(delta - observed >= observed) + 1) / (self.repetitions + 1)
            ),
        }


def paired_log_growth_bootstrap(
    values: FloatArray,
    *,
    repetitions: int = 10000,
    block_bars: int,
    seed: int,
) -> PairedLogGrowth:
    """Inputs are simple net returns on a caller-validated common clock, including CASH."""
    _validate_returns(values, repetitions, block_bars)
    logs = np.log1p(values)
    sampled = _circular_block_totals(
        logs, repetitions=repetitions, block_bars=block_bars, seed=seed
    ) / len(values)
    if not np.all(np.isfinite(sampled)):
        raise ValueError("bootstrap produced non-finite log growth")
    return PairedLogGrowth(sampled, np.mean(logs, axis=0), repetitions, block_bars)


def holm_adjust(p_values: dict[str, float]) -> dict[str, float]:
    if not p_values or any(not 0 <= value <= 1 for value in p_values.values()):
        raise ValueError("Holm requires finite probabilities")
    adjusted: dict[str, float] = {}
    previous = 0.0
    for rank, (name, value) in enumerate(sorted(p_values.items(), key=lambda item: item[1])):
        previous = min(1.0, max(previous, (len(p_values) - rank) * value))
        adjusted[name] = previous
    return adjusted
~~~~

### src/aegisquant/research/validation/saved_run_audit.py

来源：[src/aegisquant/research/validation/saved_run_audit.py](https://github.com/tORHANSxd/AegisQuant/blob/main/src/aegisquant/research/validation/saved_run_audit.py)；完整文件 SHA-256：`00f09cef4671a6f838fc1713c317c2a77c024eaa023de1097b3cdb1319d624b2`。
以下为当前完整文件（1–948 行）。


~~~~python
"""Read-only joins and arithmetic over saved simulations; never execute a strategy."""

from __future__ import annotations

import gzip
import hashlib
import json
import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Any

import polars as pl

from aegisquant.accounting.models import LotChange
from aegisquant.backtest.metrics import resample_equity
from aegisquant.backtest.models import EquityPoint
from aegisquant.data.hashing import canonical_sha256
from aegisquant.research.validation.evidence_contract import checked_path, decimal, require
from scripts.summarize_alpha_r4 import execution_reason

FILES = (
    "src/aegisquant/research/validation/saved_run_audit.py",
    "scripts/audit_alpha_v5_saved_runs.py",
    "configs/research/alpha_v5_saved_run_audit.yaml",
    "tests/alpha_v5/test_saved_run_audit.py",
    "docs/research/alpha_v5_saved_run_audit.md",
)
R5 = "artifacts/alpha_v5/20260908_research_churn_v3"
R4 = "artifacts/alpha_r4/20260908_v1"
SYMBOLS = ("BNBUSDT", "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
R4_ARMS = ("F0", "F1", "F2", "F3", "F4", "F5")
ZERO = Decimal(0)
MONEY_TOLERANCE = Decimal("1e-18")
COST_FIELDS = (
    "fee",
    "spread",
    "slippage",
    "impact",
    "funding",
    "borrow_interest",
    "settlement_fee",
    "liquidation_penalty",
)


def at(value: Any) -> datetime:
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if result.tzinfo is None or result.utcoffset() != timedelta(0):
        raise ValueError("saved evidence clocks must be explicit UTC")
    return result.astimezone(UTC)


def amount(value: Any) -> Decimal:
    return decimal(value)


@dataclass
class AuditChecks:
    counts: dict[str, dict[str, Any]] = field(default_factory=lambda: dict[str, dict[str, Any]]())

    def check(self, name: str, passed: bool, identity: str) -> None:
        row = self.counts.setdefault(name, {"checked": 0, "failed": 0, "examples": []})
        row["checked"] += 1
        if not passed:
            row["failed"] += 1
            if len(row["examples"]) < 5:
                row["examples"].append(identity)

    def equal(self, name: str, left: Decimal, right: Decimal, identity: str) -> None:
        self.check(name, abs(left - right) <= MONEY_TOLERANCE, identity)
        row = self.counts[name]
        row["maximum_absolute_residual"] = str(
            max(amount(row.get("maximum_absolute_residual", "0")), abs(left - right))
        )

    @property
    def passed(self) -> bool:
        return bool(self.counts) and all(row["failed"] == 0 for row in self.counts.values())


def _unique(rows: Sequence[dict[str, Any]], key: str, checks: AuditChecks) -> dict[str, Any]:
    values = {row[key]: row for row in rows}
    checks.check("unique_" + key, len(values) == len(rows), key)
    return values


def tag_saved_row(tags: Mapping[str, Any], row: Mapping[str, Any]) -> dict[str, Any]:
    require(not tags.keys() & row.keys(), "AQ-SAVED-EVIDENCE-TAG-COLLISION")
    return {**tags, **row}


def audit_saved_result(
    result: dict[str, Any],
    trace: list[dict[str, Any]],
    *,
    symbol: str,
    review_interval_hours: int | None,
    cost_benefit_lambda: Decimal = Decimal(1),
) -> dict[str, Any]:
    """Verify stored links, postings and marks. No engine or ledger commands are invoked."""
    checks = AuditChecks()
    spec = result["spec"]
    run_id = str(spec["run_id"])
    base, quote = symbol.removesuffix("USDT"), "USDT"
    start, end = at(spec["start_time"]), at(spec["end_time"])
    checks.check(
        "frozen_simulation_identity",
        spec["live_trading_locked"] is True
        and spec["accounting_policy_version"] == "accounting-v1"
        and spec["cost_policy_version"] == "cat-proxy-v2",
        run_id,
    )
    orders = {row["order"]["backtest_order_id"]: row for row in result["orders"]}
    checks.check("unique_orders", len(orders) == len(result["orders"]), run_id)
    fills = _unique(result["fills"], "fill_id", checks)
    by_order: dict[str, list[dict[str, Any]]] = defaultdict(list)
    trace_orders = {row["order_id"]: row for row in trace if row.get("order_id")}
    checks.check(
        "unique_trace_orders",
        len(trace_orders) == sum(bool(r.get("order_id")) for r in trace),
        run_id,
    )
    checks.check("complete_trace_order_join", set(trace_orders) == set(orders), run_id)
    checks.check("unique_trace_clock", len({at(r["time"]) for r in trace}) == len(trace), run_id)
    checks.check(
        "trace_clock_order",
        [at(r["time"]) for r in trace] == sorted(at(r["time"]) for r in trace),
        run_id,
    )
    checks.check("trace_in_period", all(start <= at(r["time"]) <= end for r in trace), run_id)
    total_cost = ZERO
    joined: list[dict[str, Any]] = []
    fill_position = ZERO
    episodes = 0
    for fill_id, fill in fills.items():
        key = fill["backtest_order_id"]
        checks.check("fill_order_exists", key in orders and key in trace_orders, fill_id)
        if key not in orders or key not in trace_orders:
            continue
        order, saved = orders[key]["order"], trace_orders[key]
        quantity = amount(fill["quantity"]["amount"])
        signed = quantity if fill["side"] == "BUY" else -quantity
        checks.check(
            "fill_units_and_ids",
            quantity > 0
            and fill["quantity"]["asset_id"] == base
            and fill["fee"]["asset_id"] == quote
            and fill["cost_breakdown"]["asset_id"] == quote
            and all(
                fill[name] == order[name]
                for name in ("client_order_id", "order_intent_id", "instrument_id", "side")
            )
            and fill["venue_order_id"] == orders[key]["venue_order_id"],
            fill_id,
        )
        checks.check(
            "fill_causal_clocks",
            at(order["decision_time"])
            == at(saved["decision_time"])
            <= at(order["submitted_at"])
            <= at(orders[key]["arrival_time"])
            <= at(fill["event_time"])
            <= at(fill["available_time"])
            <= at(fill["ingest_time"]),
            fill_id,
        )
        costs = fill["cost_breakdown"]
        fee = amount(fill["fee"]["amount"])
        reference, execution = (
            amount(fill["reference_price"]["amount"]),
            amount(fill["execution_price"]["amount"]),
        )
        adverse = sum((amount(costs[name]) for name in ("spread", "slippage", "impact")), ZERO)
        paid = sum((amount(costs[name]) for name in COST_FIELDS), ZERO)
        checks.equal(
            "reference_notional", amount(costs["gross_notional"]), quantity * reference, fill_id
        )
        checks.equal("fee_money", amount(costs["fee"]), fee, fill_id)
        checks.equal(
            "execution_price_cost_bridge", signed * (execution - reference), adverse, fill_id
        )
        by_order[key].append(fill)
        total_cost += paid
        if fill_position == 0:
            episodes += 1
        fill_position += signed
        checks.check("funded_long_fill_path", fill_position >= 0, fill_id)
        joined.append(
            {
                "run_id": run_id,
                "order_id": key,
                "fill_id": fill_id,
                "decision_time": at(saved["decision_time"]).isoformat(),
                "submitted_at": order["submitted_at"],
                "arrival_time": orders[key]["arrival_time"],
                "event_time": fill["event_time"],
                "available_time": fill["available_time"],
                "source_event_id": fill["source_event_id"],
                "reason_primary": execution_reason(saved),
                "reason": saved["reason"],
                "signed_quantity": str(signed),
                "reference_price": str(reference),
                "execution_price": str(execution),
                "gross_notional": costs["gross_notional"],
                "paid_cost": str(paid),
                "fee_asset": fill["fee"]["asset_id"],
                "fee": str(fee),
            }
        )
    for key, saved_order in orders.items():
        order, linked = saved_order["order"], by_order[key]
        quantity = sum((amount(row["quantity"]["amount"]) for row in linked), ZERO)
        checks.equal(
            "order_cumulative_fill",
            amount(saved_order["cumulative_filled_quantity"]),
            quantity,
            key,
        )
        checks.check("order_not_overfilled", quantity <= amount(order["quantity"]["amount"]), key)
        if key in trace_orders:
            row = trace_orders[key]
            signed = amount(order["quantity"]["amount"]) * (1 if order["side"] == "BUY" else -1)
            checks.equal(
                "submitted_quantity_matches_trace",
                signed,
                amount(row["signed_planned_quantity"]),
                key,
            )
            checks.equal(
                "trace_fill_notional",
                amount(row["actual_fill_notional"]),
                sum((amount(f["cost_breakdown"]["gross_notional"]) for f in linked), ZERO),
                key,
            )
            checks.equal(
                "trace_realized_execution_cost",
                amount(row["realized_execution_cost"]),
                sum(
                    (
                        sum((amount(f["cost_breakdown"][name]) for name in COST_FIELDS), ZERO)
                        for f in linked
                    ),
                    ZERO,
                ),
                key,
            )
            checks.check(
                "trace_order_outcome",
                row["order_status"] == saved_order["status"]
                and row["rejection_reason"] == saved_order["rejection_code"],
                key,
            )
    checks.check(
        "terminal_flat",
        fill_position == 0 and amount(result["positions"][-1]["quantity"]) == 0,
        run_id,
    )
    checks.check("closed_episode_count", episodes == len(result["closed_trades"]), run_id)

    records = result["ledger_records"]
    cash: dict[str, Decimal] = defaultdict(lambda: ZERO)
    lots: dict[str, dict[str, Any]] = {}
    chain = "0" * 64
    seen_fill_records: dict[str, dict[str, Any]] = {}
    snapshots: list[dict[str, Any]] = []
    external_records = 0
    for ordinal, record in enumerate(records):
        identity = record["journal_entry"]["journal_entry_id"]
        checks.check(
            "ledger_hash_chain",
            record["previous_hash"] == chain
            and record["event_hash"]
            == canonical_sha256({k: v for k, v in record.items() if k != "event_hash"}),
            identity,
        )
        chain = record["event_hash"]
        journal = record["journal_entry"]
        checks.check(
            "journal_identity",
            identity == record["command_hash"]
            and not journal["reconciliation_adjustment"]
            and journal["supersedes_entry_id"] is None,
            identity,
        )
        balancing: dict[str, Decimal] = defaultdict(lambda: ZERO)
        cash_delta: dict[str, Decimal] = defaultdict(lambda: ZERO)
        for posting in journal["postings"]:
            asset, value = posting["amount"]["asset_id"], amount(posting["amount"]["amount"])
            checks.check(
                "posting_nonnegative_and_side",
                value >= 0 and posting["side"] in {"DEBIT", "CREDIT"},
                identity,
            )
            signed = value if posting["side"] == "DEBIT" else -value
            balancing[asset] += signed
            if posting["account_id"].startswith("cash:"):
                cash_delta[asset] += signed
                cash[asset] += signed
        checks.check(
            "double_entry_by_asset",
            all(abs(value) <= MONEY_TOLERANCE for value in balancing.values()),
            identity,
        )
        source_fill = record["source_fill_id"]
        if source_fill is None:
            external_records += 1
            checks.check(
                "only_registered_initial_funding",
                ordinal == 0
                and record["entry_template_id"] == "external-transfer"
                and at(journal["event_time"]) == start
                and dict(cash_delta) == {quote: amount(spec["initial_cash"]["amount"])},
                identity,
            )
        else:
            checks.check(
                "unique_fill_ledger_link",
                source_fill in fills and source_fill not in seen_fill_records,
                identity,
            )
            seen_fill_records[source_fill] = record
            if source_fill in fills:
                fill = fills[source_fill]
                qty = amount(fill["quantity"]["amount"]) * (1 if fill["side"] == "BUY" else -1)
                checks.equal("ledger_fill_base_cash", cash_delta[base], qty, identity)
                checks.equal(
                    "ledger_fill_quote_cash",
                    cash_delta[quote],
                    -qty * amount(fill["execution_price"]["amount"])
                    - amount(fill["fee"]["amount"]),
                    identity,
                )
                checks.check(
                    "ledger_fill_clocks_and_intent",
                    record["source_order_intent_id"] == fill["order_intent_id"]
                    and record["idempotency_key"] == "simfill:" + source_fill
                    and at(journal["event_time"]) == at(fill["event_time"])
                    and at(journal["recorded_at"]) == at(fill["ingest_time"]),
                    identity,
                )
        for change in record["lot_changes"]:
            try:
                LotChange.model_validate_json(json.dumps(change))
            except ValueError:
                checks.check("lot_schema", False, identity)
                continue
            checks.check("lot_schema", True, identity)
            before, after = change["lot_before"], change["lot_after"]
            lot_id = (before or after)["position_lot_id"]
            checks.check(
                "lot_change_continuity", lots.get(lot_id) == before, identity + ":" + lot_id
            )
            for lot in (before, after):
                if lot is None:
                    continue
                opening = fills.get(lot["source_fill_id"])
                checks.check("lot_opening_fill_exists", opening is not None, lot_id)
                if opening is not None:
                    checks.check(
                        "lot_opening_fill_identity",
                        lot_id == canonical_sha256({"fill_id": opening["fill_id"], "ordinal": 0})
                        and opening["side"] == "BUY"
                        and lot["side"] == "LONG"
                        and lot["instrument_id"] == opening["instrument_id"]
                        and lot["quantity_unit"] == "BASE_ASSET"
                        and lot["quantity_asset_id"] == base
                        and lot["settlement_asset_id"] == quote
                        and lot["contract_form"] == "SPOT"
                        and amount(lot["contract_multiplier"]) == 1
                        and at(lot["opened_at"]) == at(opening["event_time"]),
                        lot_id,
                    )
                    checks.equal(
                        "lot_opened_quantity",
                        amount(lot["opened_quantity"]),
                        amount(opening["quantity"]["amount"]),
                        lot_id,
                    )
                    checks.equal(
                        "lot_entry_price",
                        amount(lot["entry_price"]),
                        amount(opening["execution_price"]["amount"]),
                        lot_id,
                    )
                    checks.check(
                        "lot_opening_fee_asset",
                        lot["opening_fee"]["asset_id"] == quote,
                        lot_id,
                    )
                    checks.equal(
                        "lot_opening_fee",
                        amount(lot["opening_fee"]["amount"]),
                        amount(opening["fee"]["amount"]),
                        lot_id,
                    )
            if after is None:
                lots.pop(lot_id, None)
            else:
                lots[lot_id] = after
        checks.equal(
            "native_inventory_matches_net_lots",
            cash[base],
            sum((amount(lot["remaining_quantity"]) for lot in lots.values()), ZERO),
            identity,
        )
        checks.check(
            "native_cash_funded",
            cash[base] >= -MONEY_TOLERANCE and cash[quote] >= -MONEY_TOLERANCE,
            identity,
        )
        snapshots.append(
            {"time": at(journal["recorded_at"]), "quantity": cash[base], "cash": cash[quote]}
        )
    checks.check(
        "all_fills_have_ledger",
        set(seen_fill_records) == set(fills) and external_records == 1,
        run_id,
    )
    checks.check(
        "ledger_information_order",
        [r["time"] for r in snapshots] == sorted(r["time"] for r in snapshots),
        run_id,
    )
    for row in joined:
        ledger = seen_fill_records.get(row["fill_id"])
        row["ledger_event_hash"] = ledger["event_hash"] if ledger else None

    trace_by_time = {at(row["time"]): row for row in trace}
    raw_curve = result["equity_curve"]
    raw_times = [at(row["time"]) for row in raw_curve]
    checks.check(
        "raw_mtm_clock",
        raw_times == sorted(set(raw_times)) and raw_times[0] == start and raw_times[-1] == end,
        run_id,
    )
    cursor = 0
    information: dict[datetime, dict[str, Any]] = {}
    for point, time in zip(raw_curve, raw_times, strict=True):
        while cursor + 1 < len(snapshots) and snapshots[cursor + 1]["time"] <= time:
            cursor += 1
        snapshot = snapshots[cursor]
        checks.check("ledger_known_before_mark", snapshot["time"] <= time, time.isoformat())
        checks.equal(
            "ledger_cash_matches_every_mtm",
            snapshot["cash"],
            amount(point["cash"]),
            time.isoformat(),
        )
        checks.equal(
            "every_mtm_funding_identity",
            amount(point["cash"]) + amount(point["position_value"]),
            amount(point["equity"]),
            time.isoformat(),
        )
        saved = trace_by_time.get(time)
        price = amount(saved["known_close"]) if saved is not None else None
        if snapshot["quantity"] == 0:
            checks.equal(
                "every_mtm_native_position_value",
                amount(point["position_value"]),
                ZERO,
                time.isoformat(),
            )
        elif price is not None:
            checks.equal(
                "every_mtm_native_position_value",
                snapshot["quantity"] * price,
                amount(point["position_value"]),
                time.isoformat(),
            )
        else:
            checks.check("held_mtm_requires_saved_price", False, time.isoformat())
        if saved is not None:
            checks.equal(
                "decision_native_quantity",
                amount(saved["current_quantity"]),
                amount(snapshot["quantity"]),
                time.isoformat(),
            )
            checks.equal(
                "decision_quote_cash", amount(saved["cash"]), snapshot["cash"], time.isoformat()
            )
        information[time] = {"quantity": snapshot["quantity"], "mark": price, "source_time": time}
    points = tuple(EquityPoint.model_validate_json(json.dumps(row)) for row in raw_curve)
    grid = resample_equity(points, 14400)
    cursor = 0
    curve: list[dict[str, Any]] = []
    for point in grid:
        while cursor + 1 < len(raw_times) and raw_times[cursor + 1] <= point.time:
            cursor += 1
        info = information[raw_times[cursor]]
        curve.append(
            {
                "time": point.time,
                "equity": point.equity,
                "cash": point.cash,
                "position_value": point.position_value,
                **info,
            }
        )

    funnel: Counter[tuple[str, str, str, str]] = Counter()
    last_review = last_submitted = None
    clock_rows = no_order_reviews = 0
    for ordinal, row in enumerate(trace, 1):
        time = at(row["time"])
        funnel[
            (
                str(row["reason"]),
                str(row.get("resize_gate_reason")),
                str(row.get("rebalance_permitted")),
                str(row["order_status"]),
            )
        ] += 1
        if row.get("rebalance_permitted") is not None and review_interval_hours is not None:
            permitted = last_review is None or time - last_review >= timedelta(
                hours=review_interval_hours
            )
            shown = (
                at(row["last_regular_review"])
                if row.get("last_regular_review") is not None
                else None
            )
            submitted_before = (
                at(row["last_resize_time_before_decision"])
                if row.get("last_resize_time_before_decision") is not None
                else None
            )
            checks.check(
                "review_due_from_previous_state",
                row["rebalance_permitted"] is permitted,
                str(ordinal),
            )
            checks.check(
                "review_state_transition",
                shown == last_review or (permitted and shown == time),
                str(ordinal),
            )
            checks.check(
                "submitted_clock_is_not_fill_clock",
                submitted_before == last_submitted,
                str(ordinal),
            )
            clock_rows += 1
            if shown == time and not row.get("order_id"):
                no_order_reviews += 1
            last_review = shown
        reason = row.get("resize_gate_reason")
        if reason in {"REBALANCE_COST_EXCEEDS_RISK_BENEFIT", "REBALANCE_RISK_BENEFIT_COVERS_COST"}:
            benefit, cost = (
                amount(row["rebalance_risk_benefit"]),
                amount(row["rebalance_cost_equity_fraction"]),
            )
            accepted = benefit > 0 and cost <= cost_benefit_lambda * benefit
            checks.check(
                "recorded_cost_benefit_veto",
                accepted is (reason == "REBALANCE_RISK_BENEFIT_COVERS_COST"),
                str(ordinal),
            )
        if row.get("order_id"):
            last_submitted = time
            if review_interval_hours is not None:
                last_review = time
    return {
        "summary": {
            "run_id": run_id,
            "status": "VERIFIED_STORED_SIMULATION"
            if checks.passed
            else "INCONSISTENT_STORED_SIMULATION",
            "orders": len(orders),
            "fills": len(fills),
            "ledger_records": len(records),
            "trace_rows": len(trace),
            "raw_mtm_points": len(raw_curve),
            "grid_points": len(grid),
            "paid_cost": str(total_cost),
            "initial_cash": spec["initial_cash"]["amount"],
            "final_cash": str(cash[quote]),
            "clock_rows_checked": clock_rows,
            "carried_mark_older_than_4h": sum(
                row["time"] - row["source_time"] > timedelta(hours=4) for row in curve
            ),
            "due_reviews_without_order": no_order_reviews,
            "checks": checks.counts,
        },
        "joins": joined,
        "curve": curve,
        "gate_funnel": [
            {
                "reason": key[0],
                "resize_gate_reason": key[1],
                "review_due": key[2],
                "order_status": key[3],
                "rows": count,
            }
            for key, count in sorted(funnel.items())
        ],
    }


def combine_segments(segments: Sequence[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for segment in segments:
        if not segment:
            raise ValueError("missing segment curve")
        if output:
            previous, current = output[-1], segment[0]
            if previous["time"] != current["time"] or any(
                previous[key] != current[key]
                for key in ("equity", "cash", "quantity", "position_value")
            ):
                raise ValueError("quarter boundary must preserve the paid exit and inherited cash")
            output.extend(segment[1:])
        else:
            output.extend(segment)
    if any(b["time"] - a["time"] != timedelta(hours=4) for a, b in pairwise(output)):
        raise ValueError("complete four-hour calendar required")
    return output


def tail_inventory(curves: Mapping[str, list[dict[str, Any]]]) -> dict[str, Any]:
    if not curves or any(
        [r["time"] for r in curve] != [r["time"] for r in next(iter(curves.values()))]
        for curve in curves.values()
    ):
        raise ValueError("tail attribution needs the same full calendar for every asset")
    symbols = sorted(curves)
    size = len(curves[symbols[0]])
    if size < 2:
        raise ValueError("tail attribution needs at least two marks")
    if any(b["time"] - a["time"] != timedelta(hours=4) for a, b in pairwise(curves[symbols[0]])):
        raise ValueError("tail attribution needs a complete four-hour calendar")
    nav = [
        sum((curves[symbol][index]["equity"] for symbol in symbols), ZERO) for index in range(size)
    ]
    if any(value <= 0 for value in nav):
        raise ValueError("tail attribution requires positive portfolio NAV")
    returns = [(nav[index] - nav[index - 1]) / nav[index - 1] for index in range(1, size)]
    rank = (len(returns) + 19) // 20
    threshold = sorted(returns)[rank - 1]
    selected = [index for index in range(1, size) if returns[index - 1] <= threshold]
    rows: list[dict[str, Any]] = []
    for index in selected:
        components: list[dict[str, Any]] = []
        total = ZERO
        for symbol in symbols:
            previous, current = curves[symbol][index - 1], curves[symbol][index]
            change = current["equity"] - previous["equity"]
            total += change
            components.append(
                {
                    "symbol": symbol,
                    "quantity_before": str(previous["quantity"]),
                    "quantity_after": str(current["quantity"]),
                    "saved_mark_before": str(previous["mark"])
                    if previous["mark"] is not None
                    else None,
                    "saved_mark_after": str(current["mark"])
                    if current["mark"] is not None
                    else None,
                    "cash_change": str(current["cash"] - previous["cash"]),
                    "position_value_change": str(
                        current["position_value"] - previous["position_value"]
                    ),
                    "equity_change": str(change),
                    "portfolio_return_contribution": str(change / nav[index - 1]),
                    "source_mark_before": previous["source_time"].isoformat(),
                    "source_mark_after": current["source_time"].isoformat(),
                    "source_age_seconds_after": str(
                        (current["time"] - current["source_time"]).total_seconds()
                    ),
                }
            )
        residual = total - (nav[index] - nav[index - 1])
        if abs(residual) > MONEY_TOLERANCE:
            raise ValueError("asset changes do not sum to portfolio change")
        rows.append(
            {
                "start": curves[symbols[0]][index - 1]["time"].isoformat(),
                "end": curves[symbols[0]][index]["time"].isoformat(),
                "net_return": str(returns[index - 1]),
                "equity_change": str(total),
                "sum_residual": str(residual),
                "assets": components,
            }
        )
    return {
        "selection": "WORST_CEIL_5_PERCENT_OF_ALL_4H_RETURNS_INCLUDING_ALL_CUTOFF_TIES",
        "observations": len(returns),
        "minimum_selected": rank,
        "threshold": str(threshold),
        "selected": len(rows),
        "rows": rows,
        "meaning": "STORED_SIMULATED_ACCOUNT_CONTRIBUTIONS_NOT_CAUSAL_FACTOR_ALPHA",
    }


def validate_config(config: Mapping[str, Any]) -> None:
    match = re.fullmatch(r"alpha-r5-saved-evidence-(\d{8})-v([1-9]\d*)", config["generation"])
    require(match is not None, "AQ-SAVED-EVIDENCE-GENERATION")
    if match is None:
        return
    require(
        config["output"] == f"artifacts/alpha_v5/{match[1]}_saved_evidence_v{match[2]}",
        "AQ-SAVED-EVIDENCE-OUTPUT",
    )
    require(
        config["scope"] == "B1_SAVED_SIMULATION_JOINS_NO_REPLAY"
        and config["saved_scope"]
        == {"r5_registered_runs": 55, "r4_registered_segments": 160, "new_strategy_runs": 0}
        and config["r4_cost_1_arms"] == list(R4_ARMS),
        "AQ-SAVED-EVIDENCE-SCOPE",
    )
    require(
        config["tail_fraction"] == "0.05"
        and config["source_period"] == ["2022-04-01T00:00:00Z", "2025-10-01T00:00:00Z"],
        "AQ-SAVED-EVIDENCE-FIXED-AUDIT",
    )


def build_documents(root: Path, sources: dict[str, Any]) -> Mapping[str, Any]:
    catalog, original = sources["b0_catalog"]["reads"], sources["b0_baseline"]["files"]
    reads: list[dict[str, Any]] = []

    def read(name: str) -> bytes:
        binding = catalog.get(name) or original.get(name)
        require(binding is not None, "AQ-SAVED-EVIDENCE-UNREGISTERED-SOURCE:" + name)
        path = checked_path(root, name)
        raw = path.read_bytes()
        require(
            hashlib.sha256(raw).hexdigest() == binding["sha256"] and len(raw) == binding["bytes"],
            "AQ-SAVED-EVIDENCE-CHANGED-SOURCE:" + name,
        )
        reads.append({"path": name, "sha256": binding["sha256"], "bytes": len(raw)})
        return raw

    r5_manifest = sources["r5_manifest"]
    tasks: list[dict[str, Any]] = []
    for run in r5_manifest["planned_runs"]:
        arm, symbol, cost = (str(run[k]) for k in ("arm", "symbol", "cost"))
        require(
            symbol in SYMBOLS
            and arm in r5_manifest["config"]["arms"]
            and cost in r5_manifest["config"]["arms"][arm]["costs"],
            "AQ-SAVED-EVIDENCE-UNREGISTERED-RUN",
        )
        settings = {**r5_manifest["config"]["resize"], **r5_manifest["config"]["arms"][arm]}
        tasks.append(
            {
                "arm": arm,
                "symbol": symbol,
                "cost": cost,
                "segment": "continuous",
                "folder": f"{R5}/runs/{arm}/{symbol}/{cost}",
                "hours": None if arm == "G0" else settings["review_interval_hours"],
            }
        )
    require(len(tasks) == 55, "AQ-SAVED-EVIDENCE-R5-SCOPE")
    r4_registry = sources["r4_registry"]
    for trial in r4_registry["trials"]:
        if trial["arm"] not in R4_ARMS or (trial["mode"], trial["cost_multiplier"]) != (
            "REDECIDE_FUNDED",
            "1",
        ):
            continue
        require(
            trial["status"] == "REPLAYED"
            and trial["symbol"] in SYMBOLS
            and len(trial["segments"]) == (14 if trial["arm"] in {"F0", "F1"} else 1),
            "AQ-SAVED-EVIDENCE-R4-SCOPE",
        )
        for segment in trial["segments"]:
            tasks.append(
                {
                    "arm": trial["arm"],
                    "symbol": trial["symbol"],
                    "cost": "1",
                    "segment": segment["segment"],
                    "folder": f"{R4}/{trial['output']}/{segment['segment']}",
                    "hours": None,
                }
            )
    require(
        len(tasks) == 215 and len({r["folder"] for r in tasks}) == 215,
        "AQ-SAVED-EVIDENCE-COMPLETE-SCOPE",
    )
    summaries: list[dict[str, Any]] = []
    joins: list[dict[str, Any]] = []
    funnels: list[dict[str, Any]] = []
    groups: dict[tuple[str, str, str], list[list[dict[str, Any]]]] = defaultdict(list)
    for index, task in enumerate(tasks, 1):
        folder = task["folder"]
        result = json.loads(gzip.decompress(read(folder + "/result.json.gz")), parse_float=str)
        trace = pl.read_parquet(read(folder + "/decision_trace.parquet")).to_dicts()
        audit = audit_saved_result(
            result,
            trace,
            symbol=task["symbol"],
            review_interval_hours=task["hours"],
            cost_benefit_lambda=amount(r5_manifest["config"]["resize"]["cost_benefit_lambda"]),
        )
        tags = {k: task[k] for k in ("arm", "symbol", "cost", "segment")}
        summaries.append(tag_saved_row(tags, audit["summary"]))
        joins.extend(tag_saved_row(tags, row) for row in audit["joins"])
        funnels.extend(tag_saved_row(tags, row) for row in audit["gate_funnel"])
        groups[(task["arm"], task["cost"], task["symbol"])].append(audit["curve"])
        if index % 10 == 0:
            print(f"saved evidence {index}/{len(tasks)} (no strategy execution)", flush=True)
    curves = {key: combine_segments(value) for key, value in groups.items()}
    require(
        all(
            curve[0]["time"] == at("2022-04-01T00:00:00Z")
            and curve[-1]["time"] == at("2025-10-01T00:00:00Z")
            for curve in curves.values()
        ),
        "AQ-SAVED-EVIDENCE-FULL-REGISTERED-PERIOD",
    )
    tails: list[dict[str, Any]] = []
    for arm, cost in sorted({(key[0], key[1]) for key in curves}):
        sleeves = {symbol: curves[(arm, cost, symbol)] for symbol in SYMBOLS}
        tails.append({"arm": arm, "cost": cost, **tail_inventory(sleeves)})
    attribution = pl.read_parquet(read(R5 + "/execution_reason_attribution.parquet")).to_dicts()
    saved_r5 = [row for row in attribution if row["arm"] in r5_manifest["config"]["arms"]]
    saved_by_fill = {row["fill_id"]: row for row in saved_r5}
    reconstructed = [row for row in joins if row["arm"] not in R4_ARMS]
    derived_checks = AuditChecks()
    derived_checks.check("unique_saved_derived_fill_ids", len(saved_by_fill) == len(saved_r5), "R5")
    derived_checks.check(
        "complete_saved_derived_fill_ids",
        set(saved_by_fill) == {row["fill_id"] for row in reconstructed},
        "R5",
    )
    for row in reconstructed:
        prior = saved_by_fill.get(row["fill_id"])
        if prior is None:
            continue
        derived_checks.check(
            "saved_reason_and_order",
            prior["reason_primary"] == row["reason_primary"]
            and prior["order_id"] == row["order_id"]
            and all(prior[key] == row[key] for key in ("arm", "symbol", "cost")),
            row["fill_id"],
        )
        for old_key, new_key in (
            ("filled_qty", "signed_quantity"),
            ("filled_notional", "gross_notional"),
            ("total_cost", "paid_cost"),
            ("fee_paid", "fee"),
        ):
            derived_checks.equal(
                "saved_derived_" + old_key,
                amount(prior[old_key]),
                amount(row[new_key]),
                row["fill_id"],
            )
    passed = (
        all(row["status"] == "VERIFIED_STORED_SIMULATION" for row in summaries)
        and derived_checks.passed
    )
    ordinary = Counter(
        (row["arm"], row["cost"], row["reason_primary"])
        for row in joins
        if row["reason_primary"] in {"ORDINARY_RISK_REDUCE", "ORDINARY_RISK_RESTORE"}
    )
    arm_costs = sorted({(row["arm"], row["cost"]) for row in summaries})
    require(len(arm_costs) == 17 and len(tails) == 17, "AQ-SAVED-EVIDENCE-ALL-17-GROUPS")
    status = "VERIFIED_STORED_SIMULATION" if passed else "INCONSISTENT_STORED_SIMULATION"
    return {
        "raw_source_inventory.json": {
            "reads": reads,
            "source_identity": "B0_HASHED_ORIGINAL_FILES_AND_R5_JOURNAL_BOUND_CATALOG",
            "new_strategy_runs": 0,
        },
        "prior_output_issues.json": {
            "source_manifest": "artifacts/alpha_v5/20260910_saved_evidence_v1/OUTPUT_MANIFEST.json",
            "status": "V1_COST_GROUP_LABELS_SUPERSEDED_BY_V2",
            "defect": "V1_ROW_COST_AMOUNT_OVERWROTE_COST_SCENARIO_TAG",
            "affected": [
                "run_summary_cost_tag",
                "fill_join_cost_tag",
                "ordinary_fill_count_groups",
            ],
            "unaffected": [
                "original_source_bytes",
                "per_run_ledger_mtm_checks",
                "twelve_tail_groups",
            ],
            "repair": "COST_SCENARIO_IN_COST_AND_MONEY_IN_PAID_COST_WITH_COLLISION_REJECTION",
            "prior_output_preserved": True,
            "new_strategy_or_significance_calculations": False,
        },
        "raw_order_fill_ledger_audit.json": {
            "status": status,
            "runs": summaries,
            "joins": joins,
            "derived_table_checks": derived_checks.counts,
        },
        "recorded_gate_funnel.json": {
            "status": "OBSERVED_RECORDED_TERMINAL_GATES_ONLY",
            "total_decisions": sum(r["trace_rows"] for r in summaries),
            "groups": funnels,
            "all_internal_gate_evaluations": "NOT_PERSISTED_CANNOT_RECONSTRUCT_SKIPPED_GATES",
            "ordinary_fill_counts": [
                {"arm": arm, "cost": cost, "reason": reason, "fills": ordinary[(arm, cost, reason)]}
                for arm, cost in arm_costs
                for reason in ("ORDINARY_RISK_REDUCE", "ORDINARY_RISK_RESTORE")
            ],
        },
        "all_worst_5pct_inventory.json": {
            "groups": tails,
            "statistical_test_or_bootstrap": False,
            "new_candidate_selection": False,
        },
        "evidence_gaps.json": {
            "still_unverified": [
                "EVERY_INTERNAL_GATE_AND_PRE_VETO_POST_SECOND_ROUNDING_TARGET",
                "EXTERNAL_ACK_CANCEL_AND_QUEUE_EVENT_STREAM",
                "INDEPENDENT_PIT_FEE_RULE_DEPTH_LATENCY",
                "CAUSAL_FACTOR_AND_EXECUTION_DECOMPOSITION_OF_TAIL",
                "COMPLETE_TRIAL_HISTORY_AND_UNUSED_HOLDOUT",
            ],
            "old_reports_preserved": True,
            "real_execution_verified": False,
            "research_conclusion": "NO_PROVEN_ALPHA",
        },
        "report.md": f"""# 全部 17 组已保存原始模拟记录只读核验

**NO_PROVEN_ALPHA / CASH；模型、纸面、实盘和订单继续关闭。**

本批核验原 R5 的全部 55 个保存结果及原 R4 的 F0–F5 共 160 个保存分区（F0/F1 各 70 个季度，F2–F5 各 5 个连续 sleeve），覆盖原汇总的全部 17 个策略/成本组；所有输入先与 B0 封存哈希核对。当前结果：**{status}**。这是读取原始模拟记录后的联结与算术核验，没有调用策略引擎、重建行情、重定价成交、训练或重新计算显著性。此前 HASH_ONLY/NOT_VERIFIED 报告保留，不能把本报告倒填成此前已经完成。

v1 的逐 run 对账和 12 组尾部核验已完成，但新汇总将成本金额与成本倍率同名为 cost，覆盖了 run/fill 的倍率标签，普通调仓表因此按金额错误分组。v1 原目录及 manifest 保留，问题详情见 prior_output_issues.json。本 v2 以 cost 记录冻结倍率、paid_cost 记录费用金额，并拒绝标签冲突；重新读取原保存数据核对元数据后才输出替代表，同时补齐 F1–F5。它没有重新运行任何原策略。

逐单核对 trace→order→fill→ledger、数量/时钟/费用资产、原账本哈希链和每资产借贷平衡，并从已有 postings 和 lot changes 核对每个已保存 MTM 的资金、原生库存和已记录价格。F0/F1 季度边界要求付费退出与下一季度初始资金一致，不能遗漏不利边界。检查逐项计数和失败示例见 raw_order_fill_ledger_audit.json；失败不会被删掉或强制改成预期数字。原 G1/1 的普通减仓为 {ordinary[("G1", "1", "ORDINARY_RISK_REDUCE")]} 笔、普通恢复为 {ordinary[("G1", "1", "ORDINARY_RISK_RESTORE")]} 笔，所有组的零计数也显式列示。

共读取 {sum(r["trace_rows"] for r in summaries)} 行决策 trace。门槛表覆盖这些行的已记录终态理由；它不是未保存的逐个内部门槛执行轨迹。复核状态从前行保存状态及提交事件核对，未下单也可能消耗到期复核。没有外部 ack/cancel/queue 流，不能据此声称真实场所时钟已验证。

最差窗口固定为每个策略/成本组完整四小时日历的最差 ceil(5%×N)，临界值并列全部保留；每个窗口列出全部五币的原生持仓、cash/position value 变化和组合收益贡献。沿用原 resample_equity 的已知标记前填规则并记录 source_time/标记年龄；网格完整不代表底层行情无缺口。只是原模拟账户贡献，不是因果因子归因或信号 alpha。没有读取新的行情，也没有事后挑选一两个故事窗口。

仍缺逐个内部门槛、veto 前和二次取整后完整目标、真实 PIT/费用/盘口/延迟、完整试验史及未使用留出。任务的完整实证验收仍未完成；所有新历史策略回放、真实收益模型拟合、真实校准拟合、最终留出读取和真实订单均为 0。
""",
    }
~~~~

### tests/alpha_v5/test_resize_semantics_contract.py

来源：[tests/alpha_v5/test_resize_semantics_contract.py](https://github.com/tORHANSxd/AegisQuant/blob/main/tests/alpha_v5/test_resize_semantics_contract.py)；完整文件 SHA-256：`50d7c426ef60b60bcb751f5e7d82098d607b31b992b1ac1c611dfb80a13edefe`。
`test_invoked_pure_functions_match_frozen_sources`，原文件第 31–37 行：


~~~~python
def test_invoked_pure_functions_match_frozen_sources(project_root: Path) -> None:
    for name in ("research/strategies/buffered_target.py", "portfolio/optimizer.py"):
        relative = f"src/aegisquant/{name}"
        frozen = (
            project_root / "artifacts/alpha_v5/20260908_research_churn_v3/implementation" / relative
        )
        assert sha256_file(project_root / relative) == sha256_file(frozen)
~~~~

### tests/architecture/test_risk_boundaries.py

来源：[tests/architecture/test_risk_boundaries.py](https://github.com/tORHANSxd/AegisQuant/blob/main/tests/architecture/test_risk_boundaries.py)；完整文件 SHA-256：`8393b78411227b0ed063990ede1cbd9a2af457818dbe64858a55b815796c2edf`。
以下为当前完整文件（1–40 行）。


~~~~python
"""P11 architecture proof that research/model code cannot own risk overrides."""

from __future__ import annotations

import ast
from pathlib import Path

import aegisquant.risk as risk_api


def test_research_and_model_packages_do_not_import_independent_risk_engine(
    project_root: Path,
) -> None:
    roots = (
        project_root / "src/aegisquant/research",
        project_root / "src/aegisquant/intelligence",
    )
    violations: list[str] = []
    for root in roots:
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [item.name for item in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                else:
                    continue
                if any(
                    name == "aegisquant.risk" or name.startswith("aegisquant.risk.")
                    for name in names
                ):
                    violations.append(path.relative_to(project_root).as_posix())
    assert violations == []


def test_public_risk_api_exposes_no_override_or_bypass_symbol() -> None:
    exported = set(risk_api.__all__)
    assert all("override" not in name.casefold() for name in exported)
    assert all("bypass" not in name.casefold() for name in exported)
~~~~

## 附录 D：关键来源哈希和下一批验收建议

本文件包含的代码片段定位如下；该清单只标识实际摘录的源码，不声称完整覆盖整个代码仓库。


~~~~json
[
  {
    "path": "src/aegisquant/research/strategies/buffered_target.py",
    "sha256": "596b7fcdd31e48f7d0b35b9f477bbfd2e2c9c6fa8ce263af180079510b1837fc",
    "ranges": [
      [
        1,
        259
      ]
    ]
  },
  {
    "path": "src/aegisquant/portfolio/optimizer.py",
    "sha256": "5cb1aed0a371b608fa71007edce183429f6e488ebfa217942b33efab8457031a",
    "ranges": [
      [
        1,
        494
      ]
    ]
  },
  {
    "path": "artifacts/alpha_v5/20260908_research_churn_v3/implementation/src/aegisquant/portfolio/optimizer.py",
    "sha256": "c52abbcaf1bbbb90715569a563fc85e57974f89e15ead33cc6db5d7e3bc033c1",
    "ranges": [
      [
        28,
        62
      ]
    ]
  },
  {
    "path": "src/aegisquant/research/validation/cat_replay.py",
    "sha256": "5d722264eb2b3d2f0366e425645fe759189ac468aa2f9f1b51dccafd30317e01",
    "ranges": [
      [
        111,
        168
      ],
      [
        199,
        907
      ]
    ]
  },
  {
    "path": "src/aegisquant/backtest/costs.py",
    "sha256": "63b70b2fcd7cc6a2033210363df03d5892d51476f834a549f08484bd9de287fb",
    "ranges": [
      [
        122,
        237
      ],
      [
        240,
        325
      ]
    ]
  },
  {
    "path": "src/aegisquant/backtest/fills.py",
    "sha256": "c59c9af68c2a81a8465d93b7d4bb699a5e276e53491b187b214883c1c5ac7190",
    "ranges": [
      [
        265,
        428
      ]
    ]
  },
  {
    "path": "src/aegisquant/accounting/ledger.py",
    "sha256": "0156449710a88645f45e9d68f470f2bd57336ce38d61ec2efc3b08b4e36b7bf3",
    "ranges": [
      [
        377,
        418
      ],
      [
        420,
        510
      ],
      [
        686,
        864
      ],
      [
        1365,
        1378
      ]
    ]
  },
  {
    "path": "src/aegisquant/research/validation/portfolio_replay.py",
    "sha256": "61c2e4148ff76956997243d4fc34d95369109d2dad621e802bda7f85b217212e",
    "ranges": [
      [
        1,
        79
      ],
      [
        205,
        352
      ],
      [
        427,
        767
      ]
    ]
  },
  {
    "path": "src/aegisquant/research/datasets/pit_universe.py",
    "sha256": "23e15f66924323e5112dfd6b381d74fa5d75f77b97edbf247e62bc9f19eaefca",
    "ranges": [
      [
        229,
        426
      ]
    ]
  },
  {
    "path": "src/aegisquant/research/validation/splits.py",
    "sha256": "6cd46de145afac6ea774489cb4ea40de82c31a68e1cca0fcf95df1b4cd83a066",
    "ranges": [
      [
        25,
        53
      ],
      [
        56,
        65
      ],
      [
        68,
        126
      ]
    ]
  },
  {
    "path": "src/aegisquant/research/validation/ml_contract.py",
    "sha256": "e40055462e924024ff301d708054284ad5152020572e80333f6d12e2eac22a55",
    "ranges": [
      [
        200,
        225
      ],
      [
        228,
        257
      ]
    ]
  },
  {
    "path": "src/aegisquant/labels/episodes.py",
    "sha256": "715722f35412bee7c7b11014e7fb3d95059b63b525a6d01c97ea21ab4e29e9b4",
    "ranges": [
      [
        59,
        129
      ]
    ]
  },
  {
    "path": "src/aegisquant/research/validation/paired_bootstrap.py",
    "sha256": "87c8e6472552b0f00f7042c2ece5dd713464d6c94924d014d1a3f92d890bb9ba",
    "ranges": [
      [
        1,
        173
      ]
    ]
  },
  {
    "path": "src/aegisquant/research/validation/saved_run_audit.py",
    "sha256": "00f09cef4671a6f838fc1713c317c2a77c024eaa023de1097b3cdb1319d624b2",
    "ranges": [
      [
        1,
        948
      ]
    ]
  },
  {
    "path": "tests/alpha_v5/test_resize_semantics_contract.py",
    "sha256": "50d7c426ef60b60bcb751f5e7d82098d607b31b992b1ac1c611dfb80a13edefe",
    "ranges": [
      [
        31,
        37
      ]
    ]
  },
  {
    "path": "tests/architecture/test_risk_boundaries.py",
    "sha256": "8393b78411227b0ed063990ede1cbd9a2af457818dbe64858a55b815796c2edf",
    "ranges": [
      [
        1,
        40
      ]
    ]
  }
]
~~~~

建议外部评审将下一批工作拆成可验证的边界：

1. 明确两个失败测试对应的模块与来源契约，修复依赖边界和证明粒度；保留冻结副本、原失败日志及安全断言含义。
2. 给出真实 PIT 与费用/规则/盘口/延迟的最小数据契约、覆盖范围和来源验证方法，先做数据质量验收。
3. 在获得独立授权和数据后，用新 generation 固定实验协议，补全调仓门槛/目标/订单/原币费用/账本的因果链与联合尾部诊断。不得原地重跑或覆盖旧证据。
4. 核对统计目标、区间和检验量一致性、共同日历及完整独立试验史；将缺失状态保留为 UNKNOWN/INSUFFICIENT_EVIDENCE。
5. 只有实证门槛和独立复核完成后才讨论 ML、共享组合风险政策或交易准入；本文件不提供任何交易授权。
