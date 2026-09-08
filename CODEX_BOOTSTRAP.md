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
最新结论从 `artifacts/alpha_v4/reports/final_go_no_go.md` 开始；原始冻结报告保留当时状态。
研究模型完成 36 次固定配置拟合，另有 6 个因校准样本不足未拟合的预定位置；没有运行盈利参数优化。
透明趋势、ML 和独立 carry 均未获准入，维持 CASH；不因阶段实现完成而进入纸面前向或实盘。
冻结工件只能校验，不能原地覆盖；最终 holdout 因缺少此前未使用的 12 个月数据而未分配，访问次数为 0。
已用开发 OOS 数据不能冒充封存集；遵循任务书 §16，保留失败证据并停止盈利参数搜索。

安全硬约束：`LIVE_TRADING = false`、`ORDER_SUBMISSION_ENABLED = false`，
实盘适配器注册表为空，不读取或要求真实 API 私钥。任何纸面模拟结论都不授权真实交易。
