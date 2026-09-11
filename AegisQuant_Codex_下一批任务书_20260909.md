# Codex 下一批任务书：R5 证据契约与 G1 机制只读审计

日期：2026-09-09。任务状态：供用户另行交付执行的有限工程范围。本文件不授权历史策略再搜索、真实模型拟合、最终留出访问或任何交易。

## 1. 目标与不可变边界

只完成总方案 B0，以及 B1 的只读诊断、合成契约测试和缺口清单。目标是让“本次究竟验证了什么、什么没验证、G1 普通调仓门槛如何工作”成为机器可检查结果。允许最终结论继续是 **NO_PROVEN_ALPHA**。

固定远端／已提交基线：

```text
d8c6d4013097f6323ab8b7a424c860ba0ccbd62b
```

固定本地研究证据：

```text
artifacts/alpha_v5/20260908_research_churn_v3/
generation = alpha-r5-research-churn-20260908-v3
primary = G1
2022-04-01T00:00:00Z <= t < 2025-10-01T00:00:00Z
```

近期证据单独保留：

```text
artifacts/current_system_recent/20260908_v3/
primary = F3, frozen R4
2026-03-08T00:00:00Z <= t < 2026-09-08T12:00:00Z
```

**严禁：** 将近期F3改名G1、拼接收益、将任一已看数据标未使用holdout；改变G1的任何参数、趋势、调仓、费用、执行或安全行为；删除H3/H10/R24/R72及失败记录；覆盖任何冻结工件；历史策略引擎回放、真实收益模型/校准器拟合；读取保护holdout根目录的文件内容；发送真实订单或测试订单；启用纸面交易、模型或订单开关；自动进入下一批。

## 2. 工作区与 Git 规则

先读 `AGENTS.md`、`CODEX_BOOTSTRAP.md`、`state/ALPHA_V4_PROJECT_STATE.yaml`，再读审阅包的 `README_FIRST.md`、`VERSION_MAP.json`、`FULL_EVIDENCE_REFERENCE.json`、`changes_since_github_main.patch`。补丁不含 untracked 新文件，必须读取相应 `repo/` 文件及冻结 implementation。

先记录：当前分支、HEAD、`git status --porcelain`、全部本地改动路径和受影响文件hash。**只在已有 main 上工作。** 非main、detached HEAD、base身份冲突、不能安全处理已有改动时保留现场并停止。不得 `reset --hard`、`clean`、强制checkout、创建新分支、派生worktree分支、归档分支、自动push；不得把独立归档的既有非main错误当成本任务顺手修复。

已有 R5 未提交改动必须保留。不能为了匹配远端，把本地新文件恢复成R4。不得把精简包补丁强行重复应用到已经有R5改动的工作区。发现工作区源码晚于或不同于冻结R5，先报告差异，并以冻结源码为审计对象；本批不把未知差异合入历史试验。

本任务不自动提交；交付diff、审计产物和测试记录。用户之后明确要求提交时仍只在main，不能提交密钥、真实账户身份或大体积重复冻结文件。

## 3. 本批预算与登记

```yaml
generation: alpha-r5-review-contract-20260909-v1
scope: READ_ONLY_EVIDENCE_AND_SYNTHETIC_CONTRACT_TESTS
report_jobs: 1
historical_strategy_engine_runs: 0
real_return_model_fits: 0
real_calibration_fits: 0
final_holdout_accesses: 0
real_orders: 0
```

新generation必须使用 exclusive claim；失败记录也保留。若已有同名任务，停止并报告，不能删目录重跑。修复失败后需要新generation及说明，不改变原结果。工程单元测试使用临时合成数据，不计为独立量化候选；本批不运行任何会加载真实市场历史再跑策略的测试或脚本。不要未经审查就运行整个项目pytest，因为部分测试／脚本可能触发真实历史重放。

所有新产物写入独立、不存在的目录，例如：

```text
artifacts/alpha_v5/20260909_review_contract_v1/
```

创建前验证它不是已有冻结目录、symlink或保护数据根的子路径。输入路径只读；入口不能默认写回`20260908_research_churn_v3`或近期R4目录。

## 4. 改动范围：优先纯新增、兼容复用

允许下列有限文件范围；确需更大改动应停下说明，不进行架构扩展。

| 文件 | 工作 |
|---|---|
| 新增 `src/aegisquant/research/validation/evidence_contract.py` | 严格证据/版本/日历/成本mode/统计estimand契约；无回测、模型、交易入口 |
| 新增 `scripts/audit_alpha_v5_evidence.py` | 薄的只读报告CLI；读取已保存汇总/CSV/manifest，输出到新目录 |
| 新增 `configs/research/alpha_v5_review_contract.yaml` | 本批来源绑定、零预算、安全状态、原比较族和缺证据策略 |
| 新增 `tests/alpha_v5/test_evidence_contract.py` | 版本、日历、资金与工件保护固定fixture |
| 新增 `tests/alpha_v5/test_resize_semantics_contract.py` | 纯方差效用、目标距离、时钟事件表、未知证据状态fixture |
| 新增 `docs/research/alpha_v5_review_contract.md` | 契约、真实读取范围、结果来源、尚未验证清单 |

可以从既有审计脚本提取**无副作用的纯汇总函数**供新入口复用，但不要导入会写旧目录或执行旧pipeline的顶层代码。提取函数导致改动范围扩大时，在报告标明理由，必须有输入/输出完全等价测试；本批不能修改 `replay_cat`、`decide_economic_transition`、`decide_buffered_target` 的行为。

复用 `experiment_registry.py` 的路径/claim思想与 `experiments/journal.py` 的哈希链，避免再建第二套独立registry真值。必要的adapter不能令旧generation重开。纯审计任务与真实策略trial使用不同kind，不把一个报告工作算成新的独立alpha候选。

## 5. 必须完成的功能

### 5.1 证据身份与缺口分类

读取并核验精简包MANIFEST。存在完整包时先核对其ZIP hash与 `FULL_EVIDENCE_REFERENCE.json`；不一致先停止原始证据处理，不能“看起来差不多”继续。完整包不存在仍可成功生成受限审阅报告，明确 `full_raw_bundle_received=false`。

证据状态至少有：

```text
VERIFIED / DERIVED_ONLY / HASH_ONLY /
NOT_RECEIVED / NOT_COLLECTED / CONFLICT
```

分别说明：本包遗漏但完整包应有的原始文件；项目尚无的真实历史费率/L2/延迟/PIT/完整trial史/未用holdout；已检查CSV和源hash；未进行逐单复算。不能把`NOT_RECEIVED`当成manifest损坏，也不能把它当PASS。

### 5.2 只读资金、日历、季度核对

对 `readable/r5_daily_equity_utc.csv` 所有策略/成本组合，不只G1，检查：唯一UTC时间、共同起止、日界间隔、明确缺口、相同初始总资金、账户资金恒等式、终值与汇总一致、季度复合与全期一致。用Decimal解析原数值；展示容差来源，禁止静默round到一致。

保留完整期末资金和统计日历的区别。近期末半日或预登记下一开盘退出边界按已保存配置解释，不能丢弃不利末段。空仓日保留，不只计算有交易期间。

对派生成交CSV核对所有arm/cost的 fill计数、reason计数、notional、cost，与汇总一致；声明它们是派生表，不是从原始逐单凭证独立重建。至少显示G1：176 fills、12普通resize且全部reduce，以及F0普通resize 1,814/2,022；数字与源表不一致时不要强制填预期值。

### 5.3 不混淆成本模式

显式保存三个mode：

```text
REDECIDE_FUNDED
FROZEN_ORDERS_FUNDED
SAME_FILL_SHADOW
```

fixed orders 不等于 fixed fills。对于funded模式不得以“费用倍率越高终值必须越低”作测试；对于same-fill影子必须保持同quantity/time/reference/inventory，并检查嵌套不利成本的单调净损益。没有对应原始fill时，只核验已有影子表，不制造新的真实fills。

报告G1-F0财富差、账面成本差以及“各自路径加回成本”的差；明确最后一项不是零成本资金回放，也不是alpha。

### 5.4 保留全部统计与失败历史

原九个比较、原raw/adjusted p、旧CI数值和bootstrap元数据必须完整导入；只澄清字段语义：均值p值和复合收益差CI属于不同estimand。**本批不重采样、不更换块长、不重新计算显著性。** DSR/PBO缺证据继续null／INSUFFICIENT，不按55次引擎回放或10,000次bootstrap填trial数。

保留R5 v1/v2失败及近期失败身份；区分工程前置失败、观察到收益的试验、重复复现。不得删除失败来让新registry完整率达到100%。

### 5.5 G1纯机制算例与原始trace缺口

读取冻结 `buffered_target.py::rebalance_risk_benefit`，可在明确不加载市场历史的单元测试中调用纯函数。验证：

```text
current=.40, raw=.30, proposed=.33,
annual_vol=.60, horizon=2days
benefit ≈ .00000896919918 NAV
illustrative cost = .07 × .0016 = .000112 NAV
cost/benefit ≈ 12.48717949
```

16bps只是合成量纲示例，不得标历史真实费用。验证移动远离raw时benefit被截到0；更接近raw时的单调距离关系；边界/非有限输入处理；lambda乘收益侧的方向。

列出但不要伪造历史结果：raw/smoothed/proposed目标冲突、复核/提交/成交时钟混用、pending及拒单是否延迟复核、第二次取整、gap后的全部指标warmup、hardexit绕过普通调仓门槛、最差四小时的各币持仓与共同冲击。完整trace缺失时输出 `NOT_VERIFIED` 与需要文件hash，不猜测拒绝次数或最差事件日期。

本批只新增trace schema和合成状态表，不修改历史trace，不为取得新字段重新回放策略。

## 6. 必须通过的测试

至少覆盖以下独立失败场景；不是要求恰好这个数量，安全fixture可以增加，但不增加真实数据实验。

1. R4 F3与R5 G1的hash/strategy/时间绑定互换即拒绝；不能拼接；不存在的G1近期结果返回NOT_COLLECTED（该试验未执行），而非0收益或误称只是漏传。
2. 共同日历重复、非UTC、漏日、混用资金模式、额外本金注入可检测；正常空仓日不删除。
3. 季度复合/终值/现金库存恒等式正常fixture通过，篡改一行明确失败。
4. same-fill影子成本恶化净损益不可改善；funded路径变化fixture不触发错误单调断言。
5. 缺完整包仍能生成受限报告；存在但hash错的包不能被当可用原始证据。
6. 旧九比较始终全部存在；compoundCI不能被改写成meanCI；未知DSR/PBO不自动赋值。
7. 输出路径复用、symlink、保护根路径、旧冻结目录均拒绝；claim重复拒绝，错误状态持久化。
8. G1效用合成值、目标距离、边界和时钟状态表与冻结文义一致；测试不调用真实历史loader。
9. 用mock/spy确认本CLI不会调用历史replay、模型fit、校准fit、持久holdout loader、订单提交或联网账户接口。
10. 运行前后所有已有冻结文件、配置参数、安全标志hash不变；不读取真实API私钥。

限定执行新增纯测试文件和明确无真实市场回放的既有契约测试。记录实际命令和结果，不引用旧1,188通过日志冒充本批通过。

## 7. 经济／统计验收与停止条件

本批无新alpha试验，因而不可能产生新的交易晋级。验收是：原算术可复核、各证据等级不混淆、全部失败保留、未知如实列示、风险/成本定义可测试。G1五churn通过和NO_PROVEN_ALPHA必须同时出现。

以下任一发生应停止对应处理并保留失败：版本/manifest冲突、原始工件被改写、跨策略拼接、原数值无法复核、保护路径被触碰、发生真实fit或历史引擎回放、任何交易开关变化、依赖需要真实凭据、为了达到预期数字修改源表。已知缺完整包不要求整个报告失败；报告范围要明确收窄。

不得因某个更高收益配置调整候选，不修改任何既有门槛。若发现新实质缺陷，先新增问题证据与最小固定反例，本批不顺手改变策略。

## 8. 交付产物

新目录至少包含：

```text
preregistration.json
source_and_version_bindings.json
evidence_contract.json
evidence_gaps.json
arithmetic_audit.json
cost_mode_audit.json
resize_semantics_cases.json
statistics_identity.json
failure_history_index.json
safety_and_budget_audit.json
report.md
validation/test_commands_and_results.txt
OUTPUT_MANIFEST.json
```

`report.md` 首部明确实际已读版本、原始行级验证未完成项、engine/fit/calibration/holdout/order计数均0；结尾给出发现列表及需要另批授权的最小下一步，但不自动执行。附Git diff与修改文件清单；不得在报告中写“全部真实执行已验证”或“可以开始交易”。

最终状态必须仍为：

```text
research_conclusion = NO_PROVEN_ALPHA
production_policy = CASH
production_ml_enabled = false
paper_trading_admitted = false
live_trading = false
order_submission_enabled = false
```

**完成本批即停止。下一批机制消融、PIT历史回放、执行实证校准、组合回放、ML训练和最终holdout，均不在本任务范围。**
