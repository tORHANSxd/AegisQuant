## 当前项目入口与 SSOT

- 当前任务方案为根目录 `AegisQuant_整改与验证方案_20260909.md`；最新结果入口为 `AegisQuant_最新结果与代码审阅包_20260911.md`。
- 启动入口为 `CODEX_BOOTSTRAP.md`，当前状态为 `state/ALPHA_V4_PROJECT_STATE.yaml`，有效约束和章节索引为 `state/SPEC_INDEX.md`。原 v4 安全与经济晋级约束继续有效，不能因删除旧文档放宽。
- 用户于 2026-09-11 明确确认删除清单中的旧任务书、包和历史工件。8,846 个跟踪文件已从工作树删除；清单与恢复说明见 `state/LATEST_ONLY_CLEANUP_PLAN.md`。
- 历史内容保存在 Git 提交 `8b6f80040f123a50faf1391710aeeeb1f2beb152`；不继续将已删除任务书或旧阶段状态当作当前执行队列。
- 保留的最新报告、研究配置与冻结源码快照维持原字节及原身份。旧路径在这些文件中仍是历史引用；涉及完整复现、源哈希或前代清单的核验，先按恢复说明取得历史快照。不得改写冻结清单、删除测试或降低断言来掩盖缺失。

## 当前结果与运行边界

- B0–B7 工程契约和合成验证已交付，汇总为 `artifacts/alpha_v5/20260910_final_contract_v1/report.md`；完整研究验收仍缺真实证据和独立授权。
- 最新保存模拟记录核验为 `artifacts/alpha_v5/20260910_saved_evidence_v2/report.md`：215 个保存运行、17 组，`VERIFIED_STORED_SIMULATION`。重新核验部分血缘需要恢复前代输入；该状态不代表真实执行验证。
- G1 历史业绩来自 `artifacts/alpha_v5/20260908_research_churn_v3/report.md`；近期报告 `artifacts/current_system_recent/20260908_v3/report.md` 对应冻结 R4 F3。最新工程源码不能冒充这些冻结业绩的运行源码，G1 最近六个月结果仍缺。
- 当前结论为 `NO_PROVEN_ALPHA`，生产 `CASH`；`LIVE_TRADING = false`、`ORDER_SUBMISSION_ENABLED = false`，实盘适配器注册表为空。生产 ML、纸面、实盘和订单均未获准入，不读取或要求真实 API 私钥。
- 真实 PIT、历史费用/规则/盘口/延迟、完整独立试验史及未使用至少十二个月留出仍不足；合成测试、只读核验或实现完成不能替代相应准入证据。
- 当前研究配置 `configs/research/aegis_alpha_v5.yaml` 和 generation `alpha-r5-research-churn-20260908-v3` 保持冻结。不得使用同一 generation 重跑、修改后冒充原试验，或把清理授权当作新研究/拟合/留出/交易授权。
- 历史重建继续标记 `RECONSTRUCTED_BASELINE`；已失败试验仍属于试验历史，不能因工作树清理而从统计中省略。
- 审阅包的全仓验证数字对应清理前快照。当前保留运行功能的检查及历史核验限制见清理记录；不得宣称当前全仓测试全部通过。

## Git 分支规则

- 所有工作与提交（包括直接提交、自动提交、独立归档和子代理操作）默认始终在 `main`。用户未明确要求创建分支时，严禁创建其他分支，包括 `codex/*`、功能分支、修复分支和 `codex-archive`。
- 普通开发、修复、提交、隔离环境、worktree 或 PR 的需求不等于创建分支授权；禁止通过 `checkout -b/-B`、`switch -c/-C`、`branch <名称>` 或自动派生分支的 `worktree add` 绕过限制。
- 工作前核对当前分支；只在不会影响用户已有改动时使用已有 `main`。`main` 缺失、当前非 `main` 或 detached HEAD 无法安全处理时，保留现场并停止依赖分支的操作，不自动重命名、删除分支、迁移提交或丢弃改动。
- 用户明确要求创建分支时，只创建其授权范围内的分支；Skill、配置默认值、工具惯例或子代理建议均不能代替用户授权。
- 已授权的独立归档可在新的独立仓库初始化默认 `main`；已有非 `main` 归档保留并报错，不自动另建分支或迁移历史。`.codex-git.toml` 仍是自动 Git 开关，本节不自动启用 Git。
