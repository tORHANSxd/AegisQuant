# AegisQuant

当前入口为 [最新结果与代码审阅包](AegisQuant_最新结果与代码审阅包_20260911.md)，
实施范围见 [整改与验证方案](AegisQuant_整改与验证方案_20260909.md)。
当前状态见 [ALPHA_V4_PROJECT_STATE.yaml](state/ALPHA_V4_PROJECT_STATE.yaml)，
规格身份与仍生效的 v4 安全、经济准入约束见 [SPEC_INDEX.md](state/SPEC_INDEX.md)。

## 最新结果

- [B0–B7 工程契约与合成验证](artifacts/alpha_v5/20260910_final_contract_v1/report.md) 已交付；完整研究验收仍缺真实数据与独立授权。
- [保存模拟记录核验 v2](artifacts/alpha_v5/20260910_saved_evidence_v2/report.md) 覆盖 215 个运行、17 组，状态为 `VERIFIED_STORED_SIMULATION`。
- [R5 G1 固定开发诊断](artifacts/alpha_v5/20260908_research_churn_v3/report.md) 是当前 G1 历史业绩来源。
- [最近六个月报告 v3](artifacts/current_system_recent/20260908_v3/report.md) 对应冻结 R4 F3；G1 最近六个月结果尚未采集。

当前结论为 **NO_PROVEN_ALPHA / CASH**。工程交付、保存记录对账与历史业绩分别说明各自证据，
不构成真实执行验证或交易授权。真实 PIT、费用/规则/盘口/延迟、完整独立试验史和此前未使用的留出仍有缺口。

## 安全与验证

仅在 `main` 工作；`LIVE_TRADING = false`、`ORDER_SUBMISSION_ENABLED = false`，
实盘适配器注册表为空，生产 ML 与纸面准入继续关闭。
Web 只读，fixture/synthetic/development 证据不能用于 Alpha Promotion。

```text
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m pyright
pnpm verify
```

上述验证不授权新策略回放、真实模型拟合、最终留出读取或订单。
2026-09-11 发布验证的两项既有测试失败及具体边界已记录在最新审阅包中，不能把本项目描述为全仓测试全部通过。

## 旧材料清理

首页与启动入口已收敛到当前交付；R4 重复 ZIP 已删除，包内 1,135 个文件的原位副本全部保留且哈希一致。
其余历史材料尚未删除，具体范围、当前依赖和影响见 [清理清单](state/LATEST_ONLY_CLEANUP_PLAN.md)。
