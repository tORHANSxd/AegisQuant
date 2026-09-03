# V5-P01 实施摘要

P01 已完成代码、契约、独立评审修复、完整 CI 和最终工件清单封口，验收结论为
`PASS_WITH_RECORDED_NEGATIVE_RESULTS`。

## 已实现

- 新增 `AtomicClaim`、`TemporalRevision`、`TruthAssessment`、`TruthState` 和 Claim 类型。
- 新增 Truth/Impact 双通道分流，观点、解释、预测和传闻不能冒充可直接核验事实。
- 新增来源修订、删除和 TruthAssessment 的强类型 PIT 查询。
- EvidenceGraph 覆盖 v5 指定节点与边，并计算独立证据数及证据依赖分数。
- `SourceIdentity` 新增 `available_time` 和 as-of 查询，schema 显式升级至 `2.0.0`。
- 新增确定性阶段证据及 Hypothesis 属性测试。
- 独立评审后补强孤立证据过滤、graph 顺序无关 hash、assessment ID 冲突拒绝、
  graph-to-assessment 绑定、identity 自动演进和 v1→v2 显式迁移。
- 修复后完整 CI 59/59 阶段通过，全量 pytest 702 passed，三浏览器 E2E 通过。

## 仍未实现

本阶段没有训练、校准或上线 Truth 模型，没有真实世界事实准确率，没有因果预测结果，
没有可交易 Alpha。所有 P01 产物均为 `DEVELOPMENT`，实盘锁保持关闭。
