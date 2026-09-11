# AegisQuant 盈利导向重构 v4 规格索引

- 当前最高优先级项目 SSOT：`AegisQuant_盈利导向重构任务书_v4.md`
- 规格版本：`alpha-v4`；规格日期：`2026-09-03`；启用日期：`2026-09-08`
- SHA-256：`36e51644b2e3bb5d9570f8dcc18c4a7136f542e9f878b3b709739aa84eb9be85`
- 总行数：1,510；本次已完整读取，保留原文件字节。
- 当前状态：`state/ALPHA_V4_PROJECT_STATE.yaml`
- 当前明确用户要求覆盖 §1 建分支示例：只在 `main` 工作；提交继续采用中文审计格式。

## 章节与实施顺序

| 起始行 | 主题 |
|---:|---|
| 11 | §0 最终技术决策与盈利定义 |
| 52 | §1 安全约束与首笔证据提交 |
| 75 | §2 Phase A：冻结预测、指标血缘与 A0–A10 失败归因 |
| 202 | §3 Phase B：标签、全部行情、MTM、经济约束、指标和委员会 |
| 443 | §4 Phase C：AegisAlpha-CAT LONG/FLAT 策略 |
| 641 | §4.6 动态全成本经济门槛 |
| 728 | §4.7 仓位、未完成订单与换手控制 |
| 813 | §5 Phase D：Walk-forward 与防过拟合 |
| 838 | §5.2 最终封存集与单次访问 |
| 887 | §6 Phase E：逐层消融 |
| 928 | §7 Phase F：独立资金费/基差策略，需先通过前置门槛 |
| 987 | §8 Phase G：事件智能仅作为风险覆盖层 |
| 1022 | §9 成本恒等式与压力测试 |
| 1084 | §10 工程、经济、统计、稳定性及 ML 晋级门槛 |
| 1151 | §11 必须新增的测试 |
| 1201 | §12 文件修改映射 |
| 1234 | §13 建议配置骨架 |
| 1315 | §14 执行顺序与提交边界 |
| 1381 | §15 最终产物与允许结论 |
| 1433 | §16 停止条件 |
| 1458 | §17 最终报告必须回答的问题 |
| 1475 | §18 参考案例与采用范围 |
| 1503 | §19 先可信回测，再毛优势、成本门槛和 ML 增量 |

## 当前证据边界

Phase A 已冻结现有 selected-policy 60,480 行预测，原始数据和报告哈希通过校验。
所选组合的 `50.0810%` 准确率与候选 `logistic_core` 的 `-38.8225%` 净复合收益来自不同策略。
亏损候选的完整原始预测未保存，不能把现有文件宣称为其冻结序列；详见
`artifacts/alpha_v4/before/current_failure_report.md`。
用户明确授权重建并保留来源标记后，已保存 `RECONSTRUCTED_BASELINE` 并复核原指标。
Phase A–E 的实现、完整归因及 14 折开发期验证已完成；最终结论为 `NO_PROVEN_ALPHA`。
Phase F 完成独立价值门槛、两腿失败恢复验证和公开资金费筛查，未获实盘历史执行资料支持，未进行 B9 合并。
Phase G 仅接入受限风险覆盖层。结果见 `artifacts/alpha_v4/reports/final_go_no_go.md`。
最终 holdout 因没有此前未使用的 12 个月数据而未分配，访问次数为 0。Live、订单提交与生产 ML 继续锁定。

用户新增的固定多币种历史对照已完成，报告为 `artifacts/alpha_v4_multi_asset/report.md`。
范围是 BTC/ETH/BNB/SOL/XRP 的同日期固定参数开发测试；BTC 证据复用，其他四币新增 150 次拟合。
该扩展未改变 v4 规格身份、原始冻结证据或交易准入结论。

## 历史实现与规格身份

最新用户授权任务为 `deep-research-report.md`，SHA-256
`fbd6038da014075e68d88eaf6aa5ffdc8d435dcef4a1e04650942be2739ec5f6`，共 1,388 行。
首批边界来自“Codex 应首先执行的补丁伪 diff”（第 1,250 行）：先研究有效性与 churn，后续 ML 分批推进。
执行 generation 为 `alpha-r5-research-churn-20260908-v3`，配置 `configs/research/aegis_alpha_v5.yaml`，
证据 `artifacts/alpha_v5/20260908_research_churn_v3/`。v1/v2 的入口失败及哈希链保留，所有策略和统计参数未变。
首批已完成 70 个旧季度分区和 5 个原 F3 连续 sleeve 精确复现、55 次预登记回放、1,188 项全仓测试。
G1 五项 churn 门槛通过，成交名义额/实际成本减少 58.54%/58.13%；盈利季度及 Holm 统计门槛仍失败。
收尾报告为 `artifacts/alpha_v5/20260908_research_churn_v3/report.md`，验证在该目录 `validation/`。
此 R5 研究扩展不改变 v4 规格身份，也不恢复旧工程 v5 状态机。缺少真实 PIT/执行历史及未使用留出，
后续完整验收仍未满足，生产 CASH 与交易锁持续生效。

此前明确授权的审计修复任务为 `AegisQuant_盈利验证修复任务书_R2_2026-09-08.md`，
SHA-256 `15ad2e6541e9e5b29306a0ba5cdc60305f12f0ce0b137dfdcc4b610cabeabe49`。
它替代前版审计计划；v4 的安全约束、未使用留出集要求与生产现金状态继续有效。
当前执行证据见 `artifacts/alpha_v4_audit/20260908_r2_v3/`；以前审计证据保留独立身份。
R2 已完成至明确停止条件，历史报告为 `artifacts/alpha_v4_audit/20260908_r2_v3/go_no_go.md`，
逐项验收为同目录 `acceptance_matrix.json`。工程验证通过，研究结论 `NO_PROVEN_ALPHA`；
最终留出集仍未分配，生产 CASH 及全部执行锁保持。

当前新增授权任务为 `AegisQuant_R4/AegisQuant_R4_低换手与连续持仓优化任务书_20260908.md`，
SHA-256 `3304ba9a85efc46bc4534c379b5dceb5d6d098bd91c7ff0b8026dc89b4767b8f`。
它替代旧实施队列与矩阵，不改变 v4 的安全及经济准入门槛。F0–F5 与成本压力已实际完成；
最新报告 `artifacts/alpha_r4/20260908_v1/go_no_go.md`，验证 `validation/actual_test_execution.json`。
F0 保持原 A1 语义，F1/F3 采用唯一 10% 数量缓冲，F2/F3 跨季度连续运行；F4/F5 为固定挑战者。
工程状态到 `REPLAYED`，未标记 `DEVELOPMENT_SUPPORTED` 或 `HOLDOUT_SUPPORTED`；结论仍为 `NO_PROVEN_ALPHA`。

v5 和 v3.1 均为历史参考，不再作为当前 SSOT，也不据旧验收结果自动通过 alpha-v4 门槛。

- v5：`AegisQuant_v5.0_Truth_Causal_AI_Forecast_Codex_Master_Plan.md`
  - SHA-256：`aee366d5fa1a8ebd7449c597e6f822535546633efc335c1ab0053333d160a255`
  - 2,799 行，V5-P00–V5-P12；状态 `state/V5_PROJECT_STATE.yaml`，证据 `reports/v5/`。
- v3.1：`AegisQuant_v3.1_Multimodal_Event_Intelligence_Codex_Master_Taskbook.md`
  与原字节副本 `docs/spec/AegisQuant_Master_Taskbook_v3_1.md`
  - SHA-256：`1265a4feeb126bf9004685b80c0aa01d053fd983079b80d5c9063abefc382d1f`
  - 7,023 行，P00–P18；状态 `state/PROJECT_PHASE_STATE.yaml`，证据 `reports/phases/`。

旧规格文件、历史状态、历史证据及其完整性测试保持历史语义；不能覆盖当前状态或授权实盘。

2026-09-11 单文件审阅入口：`AegisQuant_最新结果与代码审阅包_20260911.md`。
最新 B0–B7 工程契约汇总：`artifacts/alpha_v5/20260910_final_contract_v1/report.md`。
最新保存模拟记录核验：`artifacts/alpha_v5/20260910_saved_evidence_v2/report.md`，
generation `alpha-r5-saved-evidence-20260910-v2`，215 个保存运行、17 组，
`VERIFIED_STORED_SIMULATION`；没有新策略回放或真实执行校准。
这些工程证据补充原研究，不替换 R5 G1 或近期冻结 R4 F3 的业绩身份；完整研究验收仍未完成。
