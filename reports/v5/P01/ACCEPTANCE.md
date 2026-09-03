# V5-P01 验收记录

- Evidence Tier: `DEVELOPMENT`
- Alpha Promotion Eligible: `false`
- Decision: `PASS_WITH_RECORDED_NEGATIVE_RESULTS`
- Live Trading Locked: `true`

| Gate | 当前结果 | 证据 |
|---|---|---|
| AtomicClaim / TruthAssessment 契约完整 | PASS | `TRUTH_CONTRACT_EVIDENCE.json` 与生成 schema |
| Claim 与 Opinion 硬分离 | PASS | 负向构造返回 `AQ-TRUTH-NON-ADJUDICABLE-CLAIM-TYPE` |
| 未来修订不可进入 PIT 查询 | PASS | 确定性三时点重放与 Hypothesis 属性测试 |
| 来源复制不增加独立证据 | PASS | 2 篇同源文档得到独立证据数 1、依赖分数 0.5 |
| Hash 可复现 | PASS | graph、assessment、revision 重建 hash 一致 |
| 完整 CI | PASS | 独立评审修复后重跑：59/59 阶段通过；pytest 702 passed |
| 最终工件清单 | PASS | CI 完成后独立生成；执行路径、大小、逐文件及 artifact-set SHA-256 自检 |

独立评审发现并修复孤立证据计数、assessment ID 冲突、graph hash 顺序和 identity
演进缺口；修复后完整 CI 与新 manifest 均通过。记录的负结果仍是没有校准 Truth 模型、
没有真实世界准确率且没有已证明 Alpha；因此本结论只允许进入 V5-P02，不授权任何
Promotion、实盘或下单。
