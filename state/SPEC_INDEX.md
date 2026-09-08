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
Phase B 标签、MTM 和经济约束已实现，评估指标、委员会及 A0–A10 完整归因待完成。
最终 holdout 尚未分配或读取。Live 和订单提交继续锁定。

## 历史实现与规格身份

v5 和 v3.1 均为历史参考，不再作为当前 SSOT，也不据旧验收结果自动通过 alpha-v4 门槛。

- v5：`AegisQuant_v5.0_Truth_Causal_AI_Forecast_Codex_Master_Plan.md`
  - SHA-256：`aee366d5fa1a8ebd7449c597e6f822535546633efc335c1ab0053333d160a255`
  - 2,799 行，V5-P00–V5-P12；状态 `state/V5_PROJECT_STATE.yaml`，证据 `reports/v5/`。
- v3.1：`AegisQuant_v3.1_Multimodal_Event_Intelligence_Codex_Master_Taskbook.md`
  与原字节副本 `docs/spec/AegisQuant_Master_Taskbook_v3_1.md`
  - SHA-256：`1265a4feeb126bf9004685b80c0aa01d053fd983079b80d5c9063abefc382d1f`
  - 7,023 行，P00–P18；状态 `state/PROJECT_PHASE_STATE.yaml`，证据 `reports/phases/`。

旧规格文件、历史状态、历史证据及其完整性测试保持历史语义；不能覆盖当前状态或授权实盘。
