# 贡献约定

1. 当前 SSOT 为 `AegisQuant_盈利导向重构任务书_v4.md`，修改映射到其章节及
   `state/ALPHA_V4_PROJECT_STATE.yaml`；v5/v3.1 状态、报告和追踪矩阵保留历史含义。
2. 只使用 `main`，按任务书 §14 的提交边界推进；先冻结原始失败证据，保持 Live 锁和秘密边界。
3. Python 必须通过 Ruff、Pyright strict、pytest、Bandit 与依赖审计；Web 必须通过
   ESLint、TypeScript、Vitest、构建和 Playwright 冒烟检查。
4. 依赖使用精确版本并提交 lockfile；版本偏离任务书时必须有 ADR 和契约证据。
5. 报告实际执行结果，不把跳过、不适用或未运行伪装成通过。
6. 提交信息遵循仓库的中文审计格式。
7. 所有新报告和 Dashboard 必须显示 EvidenceTier；`FIXTURE`、`SYNTHETIC`、
   `DEVELOPMENT` 不得声明或晋升为真实 Alpha。
8. 禁止为补齐缺失预测而未经明确例外授权重训；已冻结证据不得覆盖。费用、执行和账户数据缺失时
   写明未知，不将假设标为真实 TCA，也不将开发样本重新命名为最终 holdout。
