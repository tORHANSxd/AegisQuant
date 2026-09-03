# V5-P03 验收记录

- Evidence Tier: `DEVELOPMENT`
- Alpha Promotion Eligible: `false`
- Decision: `PASS_WITH_RECORDED_NEGATIVE_RESULTS`
- Live Trading Locked: `true`

| Gate | 当前结果 | 证据 |
|---|---|---|
| 六向检索契约 | PASS | 六类 query 非空，support/contradiction 分离 |
| Agent 非投票边界 | PASS | aggregation 固定为 calibrated model，不接受 Agent vote |
| PIT revision 选择 | PASS | 最新可见 revision；未来 hit 不可见 |
| deletion / rights 边界 | PASS | tombstoned 与 `UNKNOWN`/`PROHIBITED` hit 排除 |
| official denial | PASS | `OfficialIdentityAssessment(AUTHENTIC)` + `NEGATE` |
| provenance vocabulary | PASS | 规格要求的 node/edge 类型齐全 |
| 10 articles / 1 rumor | PASS | article=10、independent=1、dependency=0.9 |
| 历史 phase hash | PASS | P00/P01/P02 冻结 manifest 文件 SHA 独立核验 |
| 独立评审 | PASS | 三路只读审查；高/中风险缺口均已修复或明确拒绝并固化语义 |
| 完整 CI | PASS | 59/59；pytest 741 passed；Python 3.14 为 653 passed；security 0 finding；三浏览器 E2E 通过 |
| 最终工件清单 | PASS | 本文件完成后生成，逐路径/大小/hash、排除元数据与 artifact-set 自检 |

记录的负结果包括无真实检索 benchmark、无独立性 precision/recall、无语义相似度校准、
无 Truth probability calibration 和无真实世界准确率。因此本结论只授权进入 V5-P04，
不授权 Promotion、实盘、下单或真实账户连接。
