# V5-P04 实施摘要

P04 已完成并通过带负结果记录的阶段验收：Truth evidence features、三候选 Council、四种
二元概率校准、完整 calibration metrics、可逆状态回放和可靠度生命周期均已实现。证据严格
标为 `DEVELOPMENT`，不用这批合成标签冒充真实世界准确率。

## 已实现

- 十五项规格特征由 P03 的 PIT evidence graph/hit、来源先验及一致性/操纵信号构成；外部标量
  统一绑定 `EvidenceFeatureInputSnapshot` 的 lineage ID/hash 与 `available_at`，hit 必须匹配图中
  的 document revision、source identity 和 content hash。
- `llm_confidence_audit_only` 不在 `MODEL_FEATURE_NAMES`，改变它不会改变模型输入。
- 58 个固定时钟样本按 28 train、8 validation、8 calibration、12 test 划分，另含 purge 与
  embargo；fold 必须由保存的 split policy 原样重算，四个有效分区完全互斥且按时间前进；
  上游标签在下一分区前可用，同一 claim 禁止跨样本重复。
- Logistic baseline、Gradient Boosting 和按 source/event/language/claim stratum 收缩的经验
  层级 Bayesian candidate 使用同一训练/验证边界。
- 本开发 fixture 由 Gradient Boosting 在 validation Brier 上胜出；选择只读取 validation，
  不读取 test 标签。
- Platt、isotonic、temperature scaling 与 beta calibration 均仅在 calibration split 拟合并
  在 test split 报告。预先指定的 Platt test Brier=`0.128671182730271`、
  LogLoss=`0.398035941417063`、ECE=`0.241412610122022`。
- 同时报告 MCE、calibration slope/intercept、precision、recall、specificity、F1、PR-AUC、
  high-confidence accuracy 和十桶 reliability diagram。
- Truth revision chain 使用显式合法迁移表，支持 `RUMOR → VERIFIED_PRIMARY → RETRACTED`；
  as-of 查询先截断可见前缀，未来坏链不会污染过去状态。
- source reliability 在 correction/retraction/false-claim rate 恶化时从 `0.9` 衰减到 `0.8235`。
- Truth model lifecycle 在版本化阈值下演示 `NORMAL → DEGRADED → RESTRICTED → RETIRED`，
  outcome availability 和累增样本量均显式绑定，且不自动恢复。
- P00–P03 manifest 通过固定文件 SHA 与内部 artifact-set 自洽检查；这只是当前工作树的回归锚，
  不是受保护远端或外部签名证明。
- 完整 CI 63/63 阶段通过：主 Python pytest 751 passed、Python 3.14 candidate 653 passed、
  security 0 finding，Web build 与 E2E 通过；最终工件清单在验收文本完成后生成并自检。

## 仍未证明

没有真实公开 claim 标签、真实 source reliability、真实 OOS 准确率、长期 calibration drift、
因果效应、市场预测、回测收益或可交易 Alpha。P04 数值只证明管线和防泄漏契约可执行。
