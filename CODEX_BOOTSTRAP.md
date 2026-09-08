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

当前 Phase A 存在原始 `logistic_core` 逐样本预测缺失。依据 §2.2，未获得该导出或用户对
重建基线的明确例外授权前，不重新训练、不进入依赖该基线的归因和策略修改。
冻结工件只能校验，不能原地覆盖；最终 holdout 尚未分配或读取，已用开发 OOS 数据不能冒充封存集。

安全硬约束：`LIVE_TRADING = false`、`ORDER_SUBMISSION_ENABLED = false`，
实盘适配器注册表为空，不读取或要求真实 API 私钥。任何纸面模拟结论都不授权真实交易。
