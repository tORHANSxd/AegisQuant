# V5-P04 验收记录

- Evidence Tier: `DEVELOPMENT`
- Alpha Promotion Eligible: `false`
- Decision: `PASS_WITH_RECORDED_NEGATIVE_RESULTS`
- Live Trading Locked: `true`

| Gate | 当前结果 | 证据 |
|---|---|---|
| PIT feature lineage | PASS | 外部标量绑定 input snapshot；claim/evidence revision 与 content hash 对回 |
| 时间 split | PASS | fold 由声明 policy 重算；train/validation/calibration/test、purge、embargo 隔离 |
| label/claim 防泄漏 | PASS | 上游标签在下一分区前可用；同一 claim 不得换 sample ID 跨分区 |
| Truth Council | PASS | Logistic baseline、Gradient Boosting、经验层级 Bayesian 同边界比较 |
| 模型选择 | PASS | 只读取 validation Brier，并执行 baseline 最小改善门槛 |
| 概率校准 | PASS | 四种方法均独立拟合；最终方法预声明为 Platt，调用方不能事后改选 |
| 校准指标 | PASS | Brier、LogLoss、ECE、MCE、slope/intercept 与十桶 reliability diagram 齐全 |
| LLM 边界 | PASS | confidence 仅为审计字段，不进入模型输入，也不是最终 probability |
| Truth 状态回放 | PASS | 显式合法迁移；支持 `RUMOR → VERIFIED_PRIMARY → RETRACTED`；未来坏链不污染过去 |
| 来源可靠度 | PASS | policy/time/count/floor 绑定；恶化只降不升 |
| 模型可靠度 | PASS | outcome availability、样本量与 policy 单调；`NORMAL → ... → RETIRED` 且不自动恢复 |
| 历史 manifest | PASS | P00–P03 固定文件 SHA 与 artifact-set 工作树内自洽；未声称外部不可篡改 |
| 独立评审 | PASS | 多轮只读攻防；发现的 fold、PIT、状态机、policy/outcome 与 traceability 缺口已修复 |
| 完整 CI | PASS | 63/63；pytest 751 passed；Python 3.14 candidate 653 passed；security 0 finding；Web E2E 通过 |
| 最终工件清单 | PASS | 本文件完成后生成，逐路径/大小/hash、排除元数据与 artifact-set 自检 |

记录的负结果包括：58 条样本均为固定 DEVELOPMENT fixture；没有真实 PIT claim 标签、真实
source reliability、真实 OOS accuracy 或长期 drift；历史 manifest 没有外部签名锚；派生 signal
lineage 尚无受保护 artifact registry 存在性证明。11 条 pytest warning 来自已知第三方弃用路径，
未转化为本阶段准确率或 Promotion 结论。

因此本结论只授权进入 `V5-P05`，不授权 Alpha Promotion、实盘、下单或真实账户连接。
