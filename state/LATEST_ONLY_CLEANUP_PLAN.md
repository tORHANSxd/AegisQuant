# 最新交付保留与旧材料清理记录

日期：2026-09-11。项目：`D:\Personal\Quantitative_Trading`。
用户已明确回复“确认删除”，接受清单范围及相关历史核验需要先从 Git 恢复证据的影响。

**已完成删除：8,846 个跟踪文件，661,246,693 字节，1,747 个空目录。**
此前另已删除100,998,950字节的重复 R4 ZIP，两次合计移除762,245,643字节工作树文件。
未跟踪文件、实际数据、私有导入和保留范围未删除；没有重写 Git 历史。
旧目录下仍有22个未跟踪日志、81,508字节，按确认清单的排除项原位保留。

## 实际删除范围

删除前工作区 `main` 干净，HEAD 为 `a95b1ed3ce79f9c5f8774be7eed41e55ef1b0e07`。
逐项核对全部目标的绝对路径、文件类型、父目录、大小及 SHA-256，均与原清单基线一致，
随后按精确文件列表删除。目录行仅包括基线跟踪文件；`reports/phases/P14/CI_RESULTS.json` 明确保留。

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

## 保留的当前交付

- 最新任务方案 `AegisQuant_整改与验证方案_20260909.md` 和最新单文件审阅包 `AegisQuant_最新结果与代码审阅包_20260911.md`，均保持原字节。
- 当前 `src/`、`scripts/`、`configs/`、`tests/`、技术契约、依赖和实际市场数据。当前导入的旧名称模块仍是运行依赖。
- `AegisQuant_Compact_Arithmetic_Audit_20260909.json`：当前 B0 的参考输入。
- `artifacts/alpha_v5/20260908_research_churn_v3/`：最新 R5 G1 固定研究。
- `artifacts/alpha_v5/20260909_review_contract_v2/`，以及 `20260910_pit_contract_v1/`、`20260910_benchmark_contract_v1/`、`20260910_execution_contract_v1/`、`20260910_portfolio_contract_v1/`、`20260910_ml_contract_v1/`、`20260910_final_contract_v1/`：各条工程契约的最新结果。
- `artifacts/alpha_v5/20260910_saved_evidence_v2/`：最新保存模拟记录核验。
- `artifacts/current_system_backtest/20260908_v1/` 和 `artifacts/current_system_recent/20260908_v3/`：不同时间范围的最新结果。
- `reports/` 中除删除表以外的运行样例与回归输入，以及 `reports/phases/P14/CI_RESULTS.json`。
- 当前状态和导航已更新；`.git`、GitHub 历史、现有本地裸仓库、`.venv`、`node_modules`、`.tools`、`.runtime` 和私有导入目录保留。

## 核验边界

删除测试及降低断言均为0。当前工作台和交易锁检查在保留输入上执行，结果记录在本文件后部。
包含旧规格、旧阶段状态或原始基准完整性的全仓测试/历史 CI，不再能仅凭当前工作树完成。

`tests/p00/test_spec_integrity.py` 读取已删除的 v3.1 原件与副本；
`tests/p00/test_v5_evidence_reset.py` 及旧阶段证据测试读取已删除的 v5/阶段状态和报告。
当前 R5 回放、基准复现和保存记录核验的部分流程仍引用 R4/多币种原始记录与前代清单，
例如 `configs/research/alpha_v5_saved_run_audit.yaml:31` 及 `saved_run_audit.py:881`。
这些检查须先恢复历史输入或完整历史快照；保留最新输出不等于所有原始血缘仍在工作树。

最新报告和审阅包保留当时的源码、业绩、哈希与验证身份，未改写为清理后的新结果。
审阅包中的1,488项通过、2项失败是清理前快照的全仓验证，不是当前全仓测试结论。
已知两项失败、失败试验史和 `NO_PROVEN_ALPHA` 均未被清理“修复”。

## 从 Git 恢复

恢复源为提交 `8b6f80040f123a50faf1391710aeeeb1f2beb152`，该提交及其历史保留在本地和 GitHub。
已逐个读取8,846个 Git blob并与删除前哈希比较：8,844个原字节直接一致；
两份旧 `failure.json` 的 Git blob使用LF，原工作树使用CRLF，转换后原哈希完全一致。
没有缺失独有内容；精确恢复需保留这一换行差异。

以下 PowerShell 示例将旧快照导出到新的临时目录，不切换当前 `main` 或创建分支：

```powershell
$legacyRoot = Join-Path $env:TEMP ('AegisQuant-before-cleanup-' + [guid]::NewGuid().ToString('N'))
$legacySource = Join-Path $legacyRoot 'source'
$legacyZip = Join-Path $legacyRoot 'source.zip'
New-Item -ItemType Directory -Path $legacyRoot | Out-Null
git archive --format=zip --output=$legacyZip 8b6f80040f123a50faf1391710aeeeb1f2beb152
if ($LASTEXITCODE -ne 0) { throw 'Git snapshot export failed' }
Expand-Archive -LiteralPath $legacyZip -DestinationPath $legacySource

$legacyCRLF = @{
  'artifacts/alpha_v4/attempts/walkforward_0001_incomplete_source_candles/failure.json' = '65f8944b2f207efeadcf6c0bcebd5e3801c870c5670df9493d7e858b06f0ead9'
  'artifacts/alpha_v4/attempts/walkforward_0002_decimal_attribution/failure.json' = '01eb41d465f0d50386685179b0423a3dd36979b105b4d1055fcccf6521823429'
}
foreach ($legacyEntry in $legacyCRLF.GetEnumerator()) {
  $legacyFile = Join-Path $legacySource $legacyEntry.Key
  $legacyText = [IO.File]::ReadAllText($legacyFile).Replace("`r`n", "`n").Replace("`n", "`r`n")
  [IO.File]::WriteAllText($legacyFile, $legacyText, [Text.UTF8Encoding]::new($false))
  if ((Get-FileHash -LiteralPath $legacyFile -Algorithm SHA256).Hash.ToLowerInvariant() -cne $legacyEntry.Value) {
    throw ('Restored hash mismatch: ' + $legacyEntry.Key)
  }
}
$legacySource
```

这是资料导出步骤。运行历史核验时，应使用该快照及其适配的解释器、依赖和工作目录；
当前代码/元数据与旧报告不能任意拼接。恢复资料不授权重新拟合模型、重复读取留出或重用冻结 generation。

## 本轮验证结果

- 删除清单与实际执行：8,846/8,846 文件，661,246,693字节；精确范围完成。
- Git 原始内容恢复：8,846/8,846可恢复，含上述两份 CRLF 文件。
- 其余3,493个跟踪文件哈希不变，仅6个当前入口/状态文档更新；没有额外文件删除或当前源码、配置、测试改动。
- 8份最新输出清单所列263个文件、74,232,770字节的大小和SHA-256全部匹配。
- 当前运行回归15项通过，覆盖工作台、只读接口、交易锁、导入副作用及配置契约。在宿主环境执行，没有跳过CPU检查。
- 历史完整性抽检 `tests/p00/test_spec_integrity.py`：1项通过、1项因已删除v3.1任务书而发生 `FileNotFoundError`。这是已确认的恢复依赖，断言未修改；不将该失败标为通过。
- 当前入口链接、状态与任务书哈希、恢复命令PowerShell语法、`git diff --check`均通过；全仓测试未重跑。
- 未运行新策略回放、真实模型/校准拟合、最终留出读取或订单。
- 独立本地归档已按配置尝试，退出码1，未产生归档提交。裸仓库 `D:\Workspace\git\Personal--Quantitative_Trading.git` 仍使用 `codex-archive`。
  [local-git-remote/SKILL.md](C:/Users/SXD/.codex/skills/local-git-remote/SKILL.md) 要求“已有非 main 归档或未指向 main 的归档 HEAD 必须保留并报错”；本次未迁移归档历史。
