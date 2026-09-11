# 仅保留最新交付：清理清单

日期：2026-09-11。项目：`D:\Personal\Quantitative_Trading`。
清理前基线：`main` 提交 `8b6f80040f123a50faf1391710aeeeb1f2beb152`，工作区原本干净；该提交已推送 GitHub。
本清单区分已完成工作和尚未执行的删除，不能将待确认项报告为已完成。

## 已完成

- 删除 `artifacts/alpha_r4/AegisQuant_R4_Evidence_20260908_v1.zip`，100,998,950 字节。
- 删除前逐项检查全部 1,135 个包成员：项目内原位副本均存在，SHA-256 全部一致；没有删除独有证据。
- ZIP 原 SHA-256：`545ae047f777d5dbaf945be026288d525bf6f469cd3c94353823198e523bc8db`。
- 精简 `README.md` 和 `CODEX_BOOTSTRAP.md` 的历代过程叙述，保留当前入口、结果身份、安全与验证边界。
- 当前状态将旧 ZIP 标为已去重，并记录可恢复的 Git 提交；冻结报告及其原始清单没有改写。

## 拟删除，尚未执行

以下共 **8,846 个 Git 跟踪文件，661,246,693 字节（约 661 MB）**。
目录行表示该前缀下基线已跟踪的文件；`reports/phases` 明确保留当前界面读取的
`reports/phases/P14/CI_RESULTS.json`。未跟踪文件、私有导入和下文保留范围不在此删除清单中。
执行前须对照基线逐项核对路径、类型和哈希；新增或发生变化的文件不得直接删除。

| 路径 | 文件数 | 字节 |
|---|---:|---:|
| `AegisQuant_v3.1_Multimodal_Event_Intelligence_Codex_Master_Taskbook.md` | 1 | 204,271 |
| `docs/spec/AegisQuant_Master_Taskbook_v3_1.md` | 1 | 204,271 |
| `AegisQuant_v5.0_Truth_Causal_AI_Forecast_Codex_Master_Plan.md` | 1 | 41,245 |
| `AegisQuant_盈利导向重构任务书_v4.md` | 1 | 43,496 |
| `AegisQuant_盈利验证修复任务书_R2_2026-09-08.md` | 1 | 46,735 |
| `deep-research-report.md` | 1 | 54,281 |
| `AegisQuant_Codex_下一批任务书_20260909.md` | 1 | 12,872 |
| `AegisQuant_Audit_Package_20260908/` | 3 | 43,241 |
| `AegisQuant_R4/` | 10 | 58,985 |
| `artifacts/alpha_v4/` | 72 | 18,687,749 |
| `artifacts/alpha_v4_multi_asset/` | 775 | 23,466,529 |
| `artifacts/alpha_v4_audit/` | 2,754 | 130,531,835 |
| `artifacts/alpha_r4/20260908_v1/` | 3,425 | 374,918,419 |
| `artifacts/alpha_v5/20260908_research_churn_v1/` | 306 | 3,936,489 |
| `artifacts/alpha_v5/20260908_research_churn_v2/` | 307 | 37,448,868 |
| `artifacts/alpha_v5/20260909_review_contract_v1/` | 14 | 5,737,213 |
| `artifacts/alpha_v5/20260910_saved_evidence_v1/` | 24 | 26,839,680 |
| `artifacts/current_system_recent/20260908_v1/` | 368 | 4,379,689 |
| `artifacts/current_system_recent/20260908_v2/` | 452 | 23,491,797 |
| `reports/phases/`，保留 `P14/CI_RESULTS.json` | 191 | 4,187,787 |
| `reports/v5/` | 136 | 6,889,205 |
| `state/PROJECT_PHASE_STATE.yaml` | 1 | 8,750 |
| `state/V5_PROJECT_STATE.yaml` | 1 | 13,286 |

## 保留范围

- 最新任务方案 `AegisQuant_整改与验证方案_20260909.md`、最新单文件审阅包 `AegisQuant_最新结果与代码审阅包_20260911.md`。
- 当前源码、脚本、配置、测试、技术契约、依赖和实际市场数据。当前源代码导入的旧名称模块仍属于运行依赖，不按名称删除。
- `AegisQuant_Compact_Arithmetic_Audit_20260909.json`：当前 B0 配置的算术参考输入。
- `artifacts/alpha_v5/20260908_research_churn_v3/`：最新 R5 G1 固定研究结果。
- `artifacts/alpha_v5/20260909_review_contract_v2/`，以及 `20260910_pit_contract_v1/`、`20260910_benchmark_contract_v1/`、`20260910_execution_contract_v1/`、`20260910_portfolio_contract_v1/`、`20260910_ml_contract_v1/`、`20260910_final_contract_v1/`：各自工程契约的最新结果，不能只按日期保留最后一个目录。
- `artifacts/alpha_v5/20260910_saved_evidence_v2/`：最新保存模拟记录核验。
- `artifacts/current_system_backtest/20260908_v1/` 与 `artifacts/current_system_recent/20260908_v3/`：不同时间范围的最新报告。
- `reports/` 中除上表范围外的运行样例与回归输入，以及 `reports/phases/P14/CI_RESULTS.json`。当前工作台需要读取这些文件。
- 当前项目状态和规格索引；清理获准后更新导航和有效约束摘要，保留历史身份说明。
- `.git`、GitHub 历史、现有本地裸仓库、`.venv`、`node_modules`、`.tools`、`.runtime` 和私有导入目录。

## 已确认的影响

1. `tests/p00/test_spec_integrity.py` 直接读取 v3.1 两份任务书并校验原始哈希；`tests/p00/test_v5_evidence_reset.py` 读取旧 v5 任务书、状态及历史报告。删除后，这些历史完整性测试需要恢复旧文件才能执行。
2. P00–P18、V5-P00–P12 的阶段证据测试及部分历史 `--check` 入口依赖旧报告。删除文件不等于这些检查已经通过；不删除测试、不降低断言来掩盖缺失。
3. 当前 R5 回放和已保存记录核验仍引用 R4/多币种基线；`configs/research/alpha_v5_saved_run_audit.yaml:31` 与 `saved_run_audit.py:881` 引用前版 v1 清单。保留最新输出不等于删除输入后还能完整重做核验。
4. 当前工作台依赖 `reports/backtests/p06-golden/` 等样例，以及 `p15_bootstrap.py:530` 所读的 P14 CI 记录；已列为保留项。
5. 最新冻结报告保留当时身份与原始字节。获准删除后，应由当前索引注明哪些历史引用已迁出工作树，不能改写旧结果或把失败试验当作从未发生。

上述跟踪文件可从基线提交恢复。需要历史完整核验时，可在指定临时目录导出该提交；不必更改当前 `main`，也不创建其他分支。
这次清理不重写 Git 历史，因此工作树体积会减少，Git 仓库历史体积不会同步缩小。

## 当前阻塞与后续动作

自动审批审查拒绝了原先约 1,500 个文件、203 MB 的批量删除，理由是范围过广且可能损失当前依赖的历史证据和可运行性；该次操作没有执行。
随后只删除了有完整重复性证明的单个 ZIP。上表其余删除仍未执行，需用户确认接受上述历史复现与完整性检查的影响。

确认后按上述明确范围删除、更新导航及约束摘要，再验证当前运行边界；实际失败和需恢复证据的检查分别报告，不把任何未执行检查标为通过。

## 本次已完成范围的验证

- 对照清理前 12,345 个跟踪文件：12,341 个哈希不变，3 个入口/状态文档修改，1 个重复 ZIP 删除；另外新增本清单。源码、测试、配置和独有冻结证据未变。
- 当前工作台与保留规格/证据完整性回归：9 项通过。沙箱首次收集遇到已有 Polars CPU 标志错误，随后在宿主环境运行同一组测试通过，没有跳过 CPU 检查或修改测试。
- 当前入口链接、状态 YAML 解析、清单 23 行数量/字节汇总和 `git diff --check` 通过。
- 本轮未重跑全仓测试；最新审阅包中已披露的两项既有失败仍保留。
- 配置要求的独立本地归档已尝试，退出码 1，未创建归档提交。裸仓库为 `D:\Workspace\git\Personal--Quantitative_Trading.git`，仍使用 `codex-archive`。
  [local-git-remote/SKILL.md](C:/Users/SXD/.codex/skills/local-git-remote/SKILL.md) 明确要求“已有非 main 归档或未指向 main 的归档 HEAD 必须保留并报错”；本次未迁移归档历史。
