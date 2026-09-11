# Codex 启动契约

当前最高优先级项目 SSOT 为 `AegisQuant_盈利导向重构任务书_v4.md`。
开始执行时完整读取该任务书；后续按问题复核相关章节，并读取：

1. `AGENTS.md` 中当前用户要求及分支规则；
2. `state/ALPHA_V4_PROJECT_STATE.yaml` 与 `state/SPEC_INDEX.md`；
3. `artifacts/alpha_v4/before/current_failure_report.md`、`run_manifest.json` 和 `metric_lineage.json`；
4. 修改涉及的实现及测试；v5/v3.1 资料只按需要作为历史实现契约参考。

当前用户要求只使用 `main`，覆盖任务书 §1 的建研究分支示例；不得再创建任何其他分支。
提交使用 `YYYY:MM:DD Codex` 和中文修改点，按任务书 §14 分隔证据、标签、回测器、经济约束和模型改动。
首个提交已仅保存原始失败证据及其 Git 字节保全规则；不能把所选组合的预测冒充亏损候选预测。

原始 `logistic_core` 逐样本预测未保存。用户已明确授权“允许重建，并保留来源标记”，
按原代码、数据、配置和 seed 重建的结果已保存至 `artifacts/alpha_v4/reconstructed_before/`，
标记 `RECONSTRUCTED_BASELINE`；该例外只覆盖旧基线重建，不允许覆盖原始冻结证据。
本轮 v4 的实现、14 折开发期验证和最终报告已经完成，最终决定 `NO_PROVEN_ALPHA`。
原 v4 结论见 `artifacts/alpha_v4/reports/final_go_no_go.md`；原始冻结报告保留当时状态。
研究模型完成 36 次固定配置拟合，另有 6 个因校准样本不足未拟合的预定位置；没有运行盈利参数优化。
透明趋势、ML 和独立 carry 均未获准入，维持 CASH；不因阶段实现完成而进入纸面前向或实盘。
冻结工件只能校验，不能原地覆盖；最终 holdout 因缺少此前未使用的 12 个月数据而未分配，访问次数为 0。
已用开发 OOS 数据不能冒充封存集；遵循任务书 §16，保留失败证据并停止盈利参数搜索。

用户随后明确要求进行 BTC 以外的历史回测；该授权覆盖固定币种扩展，不授权利润参数搜索。
五币 BTC/ETH/BNB/SOL/XRP 的 14 折固定参数对照已完成，该历史报告为
`artifacts/alpha_v4_multi_asset/report.md`。新增 150 次拟合、18 次因校准不足跳过；
BTC 基准重用原 36 次拟合结果，合计固定开发拟合 186 次。五币组合仍为 `NO_PROVEN_ALPHA`。
原 BTC 报告及其 36/42 拟合口径保留为历史实验结果；组合报告明确披露固定存活币种、
季度独立资金基准与高成本拒单引起的成交路径变化，不把这些结果当作新的最终封存集。

安全硬约束：`LIVE_TRADING = false`、`ORDER_SUBMISSION_ENABLED = false`，
实盘适配器注册表为空，不读取或要求真实 API 私钥。任何纸面模拟结论都不授权真实交易。

用户此前要求按 `AegisQuant_盈利验证修复任务书_R2_2026-09-08.md` 执行审计与修复；
R2 完整包含前版审计主线，不另行重复两套任务。v4 安全与经济准入约束继续有效。
本地执行状态见 `state/ALPHA_V4_PROJECT_STATE.yaml` 的 `audit_r2_20260908`，
R2 证据目录为 `artifacts/alpha_v4_audit/20260908_r2_v3/`。
前版已完成实验保留在 `artifacts/alpha_v4_audit/20260908_v1/`，不得改名冒充 R2 结果。
R2 已完成至任务书的经济与证据停止条件，历史结论从
`artifacts/alpha_v4_audit/20260908_r2_v3/go_no_go.md` 和 `acceptance_matrix.json` 开始。
全仓 1,147 项测试通过；795 个旧文件哈希不变，B3/B5/B6/B7 的 280 个分区精确复现。
本次 R2 收益模型及校准器拟合均为 0，前版 62 次常数校准有独立登记。
无 ML 风险趋势和主 ML 挑战者均未满足全部准入门槛，维持 `NO_PROVEN_ALPHA` 和 CASH。
未使用留出集、完整试验历史及真实执行证据仍有缺口；不得按看过的结果重选主候选或扩大参数搜索。

用户随后明确授权执行 `AegisQuant_R4/AegisQuant_R4_低换手与连续持仓优化任务书_20260908.md`。
R4 替代此前实施队列，保留 v4 安全、冻结证据及经济晋级约束。固定 F0–F5 已完成，
最新报告为 `artifacts/alpha_r4/20260908_v1/go_no_go.md`，状态为 `r4_20260908`。
矩阵共 150 个币种成本场景、800 次引擎运行；原 A1 70 分区及集成后 F0 精确复现。
1,156 项全仓测试、40 项参考组件测试及 BTC 两个连续配置的 28 次季度事件日志恢复核验通过。
F3 缓冲与连续持仓降低实际费用，但经济门槛未全过；F4 更高总收益主要出现在信号尚未共同就绪的时段，
不能宣称多周期信号增量成立。没有新模型/校准拟合或留出访问，仍为 `NO_PROVEN_ALPHA` 和 CASH。
证据包见 `artifacts/alpha_r4/AegisQuant_R4_Evidence_20260908_v1.zip`；所有基线与失败运行记录保留。

用户最新授权以 `deep-research-report.md` 作为任务书开始修改。该报告优先执行研究有效性与 churn；
当前研究配置为 `configs/research/aegis_alpha_v5.yaml`，generation 为 `alpha-r5-research-churn-20260908-v3`。
首批状态见 `state/ALPHA_V4_PROJECT_STATE.yaml` 的 `r5_research_churn_20260908`；
执行记录在 `artifacts/alpha_v5/20260908_research_churn_v3/`。历史工程 v5 的规格及状态不因此重新启用。
`scripts/run_alpha_v5_research.py` 只提供预注册、固定无 ML 开发诊断和保存结果审计。
原始 BTC/ETH 文件包含 2025Q4，本批先生成 `[2021-01-01, 2025-10-01)` 的独立有哈希开发副本，
在实际加载前检查路径和哈希；最终留出路径始终拒绝普通研究入口访问。
前两代入口失败记录保留；禁止据此删除试验、隐瞒失败或事后重选参数。
首批现已完成，最新报告为 `artifacts/alpha_v5/20260908_research_churn_v3/report.md`。
70 个旧季度分区及 5 条原 F3 连续回放精确复现，55 次预登记回放、61 条完整时间轴核验完成。
1,188 项全仓测试和类型检查通过；本轮 13 个 Python 文件格式通过，全仓有一个未修改的既有格式问题。
G1 五项 churn 门槛均通过，换手名义额/实际成本相对 F0 减少 58.54%/58.13%；
盈利季度仍只有 6/14，全部预登记配对比较未通过 Holm 校正，继续 `NO_PROVEN_ALPHA`、CASH 和全部交易锁。
真实 PIT 数据与执行证据缺失时，这些诊断不能通过完整晋级链。首批完成不等于整份八周整改任务书完成，
也不授权 ML 重训、最终盲测、纸面交易或实盘。

2026-09-11 发布与审阅入口更新：
`AegisQuant_最新结果与代码审阅包_20260911.md` 汇总最新代码、冻结业绩、验证及未完成项。
后续 B0–B7 的工程契约和合成验证已交付，汇总见
`artifacts/alpha_v5/20260910_final_contract_v1/report.md`；完整研究验收仍受真实数据与独立授权约束。
更新后的原始记录核验见 `artifacts/alpha_v5/20260910_saved_evidence_v2/report.md`，
覆盖 215 个保存运行、17 个策略/成本组，状态为 `VERIFIED_STORED_SIMULATION`。
它补足旧报告当时未验证的原始模拟记录联结，但不改变旧报告历史身份，不代表真实执行已验证。
v1 的成本倍率/金额标签冲突及其全部工件保留；v2 分离 `cost` 与 `paid_cost` 后重新只读核验。
本批没有新增历史策略回放、真实模型/校准拟合、最终留出读取或订单。
真实 PIT/费用/规则/盘口/延迟、完整试验史及未使用留出仍缺；G1 最近六个月结果仍未采集。
最新工程实现不可冒充冻结 R5 或近期 R4 业绩的运行源码，生产继续 CASH，交易锁保持。
