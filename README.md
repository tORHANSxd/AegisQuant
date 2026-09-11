# AegisQuant

当前入口为 [最新结果与代码审阅包](AegisQuant_最新结果与代码审阅包_20260911.md)，
任务方案为 [整改与验证方案](AegisQuant_整改与验证方案_20260909.md)。
当前状态见 [ALPHA_V4_PROJECT_STATE.yaml](state/ALPHA_V4_PROJECT_STATE.yaml)，
有效约束和章节索引见 [SPEC_INDEX.md](state/SPEC_INDEX.md)。

## 最新结果

- [B0–B7 工程契约与合成验证](artifacts/alpha_v5/20260910_final_contract_v1/report.md) 已交付；完整研究验收仍缺真实数据与独立授权。
- [保存模拟记录核验 v2](artifacts/alpha_v5/20260910_saved_evidence_v2/report.md) 覆盖 215 个运行、17 组，状态为 `VERIFIED_STORED_SIMULATION`。
- [R5 G1 固定开发诊断](artifacts/alpha_v5/20260908_research_churn_v3/report.md) 是当前 G1 历史业绩来源。
- [最近六个月报告 v3](artifacts/current_system_recent/20260908_v3/report.md) 对应冻结 R4 F3；G1 最近六个月结果尚未采集。

当前结论为 **NO_PROVEN_ALPHA / CASH**。真实 PIT、费用/规则/盘口/延迟、完整独立试验史和未使用留出仍有缺口。
工程交付、保存记录对账与历史业绩分别说明各自证据，不构成真实执行验证或交易授权。

## 当前验证入口

```text
.venv\Scripts\python.exe -m pytest -q tests/integration/test_p15_workbench.py tests/security/test_live_lock.py
```

只读工作台的输入与交易锁保留。包含历史工件完整性检查的全仓测试、旧阶段 CI 和部分复现入口，
需要先按[恢复说明](state/LATEST_ONLY_CLEANUP_PLAN.md)取得历史快照。
审阅包中的 1,488 项通过、2 项失败属于清理前验证，不能作为当前全仓测试结果。

仅在 `main` 工作；`LIVE_TRADING = false`、`ORDER_SUBMISSION_ENABLED = false`，
实盘适配器注册表为空，生产 ML 与纸面准入继续关闭。
当前清理不授权新策略回放、真实模型拟合、最终留出读取或订单。

## 已完成的旧材料清理

已按确认清单删除 8,846 个旧任务书、包内文件和历史工件（661,246,693 字节），清理 1,747 个空目录；
此前还删除了约 101 MB 的重复 ZIP。当前源码、配置、测试、实际数据和各条研究链的最新结果保留。

最新报告与审阅包保留原字节；其中已删除的旧路径应从 Git 历史读取。
具体清理范围、保留项和恢复方式见[清理记录](state/LATEST_ONLY_CLEANUP_PLAN.md)。
