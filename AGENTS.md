## 当前项目 SSOT

- 项目最高优先级工程与研究 SSOT 为根目录 `AegisQuant_盈利导向重构任务书_v4.md`。
- 当前用户明确要求优先：只在 `main` 工作，不执行任务书 §1 的研究分支创建命令；提交信息仍遵循中文审计格式。
- 启动入口为 `CODEX_BOOTSTRAP.md`，当前状态为 `state/ALPHA_V4_PROJECT_STATE.yaml`，规格身份及章节索引为 `state/SPEC_INDEX.md`。
- v5、v3.1 任务书、阶段状态及报告保留为历史实现与证据；存在冲突时以 v4 和当前明确用户要求为准，不继续用旧阶段状态推进新任务。
- 执行顺序遵循 v4 §14；先冻结失败证据，禁止在 §2.2 未满足时偷偷重训或把重建预测当作原始预测。实际缺口必须写入状态和报告。
- `LIVE_TRADING = false`、`ORDER_SUBMISSION_ENABLED = false`、实盘适配器注册表为空；不读取或要求真实 API 私钥。
- v4 本轮最终结论为 `NO_PROVEN_ALPHA`；以 `artifacts/alpha_v4/reports/final_go_no_go.md` 和当前状态核对结果。模型、carry 与纸面前向均未获准入，不能把实现完成或旧阶段通过解释为交易授权。
- 用户随后授权的固定五币历史扩展已完成，历史研究报告为 `artifacts/alpha_v4_multi_asset/report.md`，结论仍为 `NO_PROVEN_ALPHA`。原 BTC 冻结报告保留；不把新增币种测试解释为参数搜索、最终留出验证或交易授权。
- R2 审计修复依据为 `AegisQuant_盈利验证修复任务书_R2_2026-09-08.md`，历史证据保留在 `artifacts/alpha_v4_audit/20260908_r2_v3/`，前版审计工件独立保留。
- R2 审计已完成至明确停止条件，历史总报告为 `artifacts/alpha_v4_audit/20260908_r2_v3/go_no_go.md`。1,147 项测试通过，B3/B5/B6/B7 的 280 个旧分区复现一致；R2 未新拟合收益模型或校准器。
- 用户随后授权执行 `AegisQuant_R4/AegisQuant_R4_低换手与连续持仓优化任务书_20260908.md`，替代旧实施队列；v4 安全和经济晋级约束继续有效。R4 已完成 F0–F5 固定六配置及成本压力的 800 次矩阵引擎回放，最新报告为 `artifacts/alpha_r4/20260908_v1/go_no_go.md`，当前状态见 `state/ALPHA_V4_PROJECT_STATE.yaml` 的 `r4_20260908`。
- R4 原 A1 70 分区及集成后 F0 逐单/成交/完整 MTM 复现一致，1,156 项全仓测试、40 项参考测试、28 次 BTC 季度事件日志恢复核验通过。R4 新模型/校准拟合和最终留出访问均为 0；F3/F4 未通过全部经济与统计门槛，仍为 `NO_PROVEN_ALPHA`，生产 CASH、ML/纸面/实盘/订单继续关闭。原 A1/A3/A7 证据不覆盖，不把缓冲省费或 F4 更高历史收益当作已证明信号增量。

## 深度审计任务书后续授权

- 用户明确授权以 `deep-research-report.md` 开始修改，并使用 Ponytail 与 workflow；按该报告“第一批只修研究有效性和 churn”的顺序执行。v4 安全及晋级约束继续有效。
- 当前 generation 为 `alpha-r5-research-churn-20260908-v3`，配置为 `configs/research/aegis_alpha_v5.yaml`，入口为 `python -m scripts.run_alpha_v5_research`，证据在 `artifacts/alpha_v5/20260908_research_churn_v3/`。此处 R5 研究 generation 与历史工程 v5 任务书是不同身份。
- v1 数据区间守卫失败、v2 严格 Decimal 配置恢复失败均保留；新策略回放前修复入口，策略参数及比较集合未改变。不得删失败记录、使用旧 generation 重跑或更改冻结策略后继续原试验。
- 首批已完成：70 个原 A1 季度分区及 5 个原 F3 连续 sleeve 精确复现，55 次预登记回放完成；1,188 项全仓测试、类型检查和本轮 13 个 Python 文件格式检查通过。61 条新旧曲线的完整四小时/UTC 日历核验通过。全仓格式检查仅有未修改的 `scripts/run_alpha_v4_final_holdout.py` 既有问题。
- 最新报告为 `artifacts/alpha_v5/20260908_research_churn_v3/report.md`。G1 五项 churn 门槛通过，相对 F0 成交名义额减少 58.54%、实际成本减少 58.13%；但盈利季度仅 6/14，全部预登记比较的 Holm 校正 p 值大于 0.05，仍为 `NO_PROVEN_ALPHA`。生产 CASH，ML/纸面/实盘/订单继续关闭，未训练新模型或读取最终留出。
- 首批仅做固定存活五币开发诊断；PIT 选样组件测试不能冒充真实 PIT universe。真实历史费用/规则/盘口/延迟、未使用至少十二个月留出及完整独立试验历史仍缺。后续 ML、组合风险、成本实证和准入阶段按各自证据门槛推进。

## Git 分支规则

- 所有工作与提交（包括直接提交、自动提交、独立归档和子代理操作）默认始终在 `main`。用户未明确要求创建分支时，严禁创建其他分支，包括 `codex/*`、功能分支、修复分支和 `codex-archive`。
- 普通开发、修复、提交、隔离环境、worktree 或 PR 的需求不等于创建分支授权；禁止通过 `checkout -b/-B`、`switch -c/-C`、`branch <名称>` 或自动派生分支的 `worktree add` 绕过限制。
- 工作前核对当前分支；只在不会影响用户已有改动时使用已有 `main`。`main` 缺失、当前非 `main` 或 detached HEAD 无法安全处理时，保留现场并停止依赖分支的操作，不自动重命名、删除分支、迁移提交或丢弃改动。
- 用户明确要求创建分支时，只创建其授权范围内的分支；Skill、配置默认值、工具惯例或子代理建议均不能代替用户授权。
- 已授权的独立归档可在新的独立仓库初始化默认 `main`；已有非 `main` 归档保留并报错，不自动另建分支或迁移历史。`.codex-git.toml` 仍是自动 Git 开关，本节不自动启用 Git。
