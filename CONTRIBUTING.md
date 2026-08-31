# 贡献约定

1. 先把规格条款映射到 `state/REQUIREMENTS_TRACEABILITY.csv`。
2. 只修改当前阶段范围，保持 Live 锁和秘密边界。
3. Python 必须通过 Ruff、Pyright strict、pytest、Bandit 与依赖审计；Web 必须通过
   ESLint、TypeScript、Vitest、构建和 Playwright 冒烟检查。
4. 依赖使用精确版本并提交 lockfile；版本偏离任务书时必须有 ADR 和契约证据。
5. 报告实际执行结果，不把跳过、不适用或未运行伪装成通过。
6. 提交信息遵循仓库的中文审计格式。
