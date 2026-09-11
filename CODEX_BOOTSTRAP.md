# Codex 启动契约

从以下当前入口开始，按任务读取相关章节与实现：

1. `AGENTS.md`：用户要求、分支规则及安全边界。
2. `AegisQuant_整改与验证方案_20260909.md`：当前任务方案；未获授权的研究阶段不自动执行。
3. `AegisQuant_最新结果与代码审阅包_20260911.md`：最新保留交付的源码、结果和问题快照。
4. `state/ALPHA_V4_PROJECT_STATE.yaml` 与 `state/SPEC_INDEX.md`：实际状态、有效约束及章节索引。
5. 当前任务涉及的源代码和测试。

原 v4 的安全、经济与统计晋级约束继续有效，已在当前索引保留并指向历史原文。
只在 `main` 工作，不创建其他分支；提交采用 `YYYY:MM:DD Codex` 和中文修改点。

## 当前交付与证据

- B0–B7 工程契约：`artifacts/alpha_v5/20260910_final_contract_v1/report.md`。
- 保存记录核验 v2：`artifacts/alpha_v5/20260910_saved_evidence_v2/report.md`。
  215 个运行、17 组，`VERIFIED_STORED_SIMULATION`；不代表真实执行已验证。
- G1 历史业绩：`artifacts/alpha_v5/20260908_research_churn_v3/report.md`。
- 最近六个月冻结 R4 F3：`artifacts/current_system_recent/20260908_v3/report.md`。
  最新工程源码不能冒充这些冻结业绩的实际运行源码；G1 最近六个月结果仍缺。
- 冻结研究配置：`configs/research/aegis_alpha_v5.yaml`，
  generation 为 `alpha-r5-research-churn-20260908-v3`。

当前结论为 `NO_PROVEN_ALPHA`，生产 `CASH`。
`LIVE_TRADING = false`、`ORDER_SUBMISSION_ENABLED = false`，
实盘适配器注册表为空，ML/纸面/实盘/订单均未获准入，不读取或要求真实 API 私钥。
缺少真实 PIT/执行历史、完整试验史和未使用留出时不能晋级。

冻结 generation 不得复用、原地重跑或修改后冒充原实验。
历史重建保持 `RECONSTRUCTED_BASELINE` 标记；失败试验不能在统计或报告中当作从未发生。
清理不授权新回放、模型/校准拟合、最终留出访问或订单。

## 历史引用与验证边界

用户已确认的 8,846 个旧文件和前批重复 ZIP 已删除，当前源码、运行输入及最新结果保留。
`state/LATEST_ONLY_CLEANUP_PLAN.md` 记录实际范围、验证与从 Git 恢复的方法。
原任务书、旧阶段状态和被删除工件不再是工作树中的当前文件。

保留报告、配置和冻结源码里的旧路径仍表示其历史血缘；不得修改冻结哈希来伪装清理后的完整性。
需要复现、源哈希或前代清单的核验时，先恢复完整历史快照，不能删除测试或降低断言。
审阅包的全仓验证数字对应清理前快照；当前状态以清理记录中的实际检查为准。
