# Codex 启动契约

从以下当前入口开始，按任务读取相关章节与实现：

1. `AGENTS.md`：用户要求、分支规则及安全边界。
2. `AegisQuant_最新结果与代码审阅包_20260911.md`：最新交付、证据身份、已知失败及未完成项。
3. `AegisQuant_整改与验证方案_20260909.md`：后续整改范围；未获授权的研究阶段不自动执行。
4. `state/ALPHA_V4_PROJECT_STATE.yaml` 与 `state/SPEC_INDEX.md`：实际状态、规格身份及章节索引。
5. 当前任务涉及的源代码和测试。

v4 任务书的安全、经济与统计准入约束继续有效；历史规格和阶段状态不再作为待实施队列。
当前工作只在 `main`；不创建其他分支。提交采用 `YYYY:MM:DD Codex` 和中文修改点。

## 当前交付与证据

- B0–B7 工程契约：`artifacts/alpha_v5/20260910_final_contract_v1/report.md`。
- 保存记录核验 v2：`artifacts/alpha_v5/20260910_saved_evidence_v2/report.md`。
  215 个运行、17 组，`VERIFIED_STORED_SIMULATION`，不代表真实执行已验证。
- G1 历史业绩：`artifacts/alpha_v5/20260908_research_churn_v3/report.md`。
- 最近六个月冻结 R4 F3：`artifacts/current_system_recent/20260908_v3/report.md`。
  最新工程源码不能冒充这些冻结业绩的实际运行源码；G1 最近六个月结果仍缺。
- 当前研究配置：`configs/research/aegis_alpha_v5.yaml`，
  generation 为 `alpha-r5-research-churn-20260908-v3`。

当前结论仍为 `NO_PROVEN_ALPHA`，生产 `CASH`。
`LIVE_TRADING = false`、`ORDER_SUBMISSION_ENABLED = false`，
实盘适配器注册表为空，ML/纸面/实盘/订单均未获准入。
不读取或要求真实 API 私钥。缺少真实 PIT/执行历史、完整试验史和未使用留出时不能晋级。

冻结 generation 不得复用、原地重跑或修改后冒充原实验。
历史基线重建保持 `RECONSTRUCTED_BASELINE` 标记；失败试验不能在统计或报告中当作从未发生。
本次清理不授权新回放、模型/校准拟合、最终留出访问或订单。

## 清理状态

2026-09-11 用户要求删除旧任务书、包及历史材料，仅保留最新交付。
已核对并删除逐字节重复的 R4 ZIP，原位文件和独立 Git 历史仍在。
其余删除项尚未执行：旧任务书、历史工件与当前验证存在依赖。
执行前读取 `state/LATEST_ONLY_CLEANUP_PLAN.md` 的明确范围与影响，
不能将待确认项报告为已清理，也不能删除测试或降低断言来掩盖缺失证据。
