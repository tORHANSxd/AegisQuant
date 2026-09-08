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

用户当前要求按 `AegisQuant_盈利验证修复任务书_R2_2026-09-08.md` 执行审计与修复；
R2 完整包含前版审计主线，不另行重复两套任务。v4 安全与经济准入约束继续有效。
本地执行状态见 `state/ALPHA_V4_PROJECT_STATE.yaml` 的 `audit_r2_20260908`，
R2 证据目录为 `artifacts/alpha_v4_audit/20260908_r2_v3/`。
前版已完成实验保留在 `artifacts/alpha_v4_audit/20260908_v1/`，不得改名冒充 R2 结果。
R2 已完成至任务书的经济与证据停止条件，最新结论从
`artifacts/alpha_v4_audit/20260908_r2_v3/go_no_go.md` 和 `acceptance_matrix.json` 开始。
全仓 1,147 项测试通过；795 个旧文件哈希不变，B3/B5/B6/B7 的 280 个分区精确复现。
本次 R2 收益模型及校准器拟合均为 0，前版 62 次常数校准有独立登记。
无 ML 风险趋势和主 ML 挑战者均未满足全部准入门槛，维持 `NO_PROVEN_ALPHA` 和 CASH。
未使用留出集、完整试验历史及真实执行证据仍有缺口；不得按看过的结果重选主候选或扩大参数搜索。
