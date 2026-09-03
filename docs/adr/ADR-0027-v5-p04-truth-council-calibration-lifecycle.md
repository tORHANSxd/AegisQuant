# ADR-0027：V5-P04 Truth Council、校准与可靠度生命周期

- 状态：Accepted
- 日期：2026-09-03
- 决策范围：Evidence Features、Truth Council、Calibration、Truth State、Reliability Decay

## 背景

LLM 自报 confidence、网页数量和来源等级都不是经过校准的事实概率。若训练、校准和测试标签
混在一起，再漂亮的 reliability diagram 也只是数据泄漏画出来的壁纸。另一方面，消息会修订、
撤稿，来源和模型也会退化，Truth 不能被固化成一次性布尔值。

## 决策

1. 从 P03 已选择的 PIT evidence graph/hit 提取规格规定的十五项模型特征；外部可靠度与
   consistency/manipulation 标量必须先进入带 lineage ID/hash 和 `available_at` 的
   `EvidenceFeatureInputSnapshot`。retrieval hit 必须与图中的 document revision、source identity
   和 content hash 一致；LLM confidence 仅作为 `llm_confidence_audit_only` 留档，明确排除在
   `MODEL_FEATURE_NAMES` 外。
2. 用时间有序且互斥的 train、validation、calibration、test 分区：train 拟合模型，validation
   选择 Logistic baseline、Gradient Boosting 或经验层级 Bayesian candidate，calibration 单独
   拟合校准器，test 只做最终评估。传入 fold 必须能由随报告保存的 split policy 原样重算，
   train/validation/calibration 的标签必须在下一分区开始前可用，同一 claim 不得换 sample ID
   跨分区重复。
3. 复杂候选只有 validation Brier 至少改善版本化阈值才可击败 Logistic baseline；test 标签和
   test 指标不得参与模型或校准方法选择。P04 的最终校准器在代码中预声明为 Platt，调用方
   不能看完 test 再传入另一个方法。
4. 二元 Truth probability 比较 Platt/logistic、isotonic、temperature scaling 和 beta
   calibration，并报告 Brier、LogLoss、ECE、MCE、calibration slope/intercept、reliability
   diagram 及分类指标。时间序列 conformal interval 方法留在 V5-P09，不伪装成点概率校准。
5. Truth 状态以 evidence revision、前驱 ID/hash 和 PIT 时间形成 append-only 链，使用显式
   合法迁移表，支持 `RUMOR → VERIFIED_PRIMARY → RETRACTED` 以及同类证据驱动修订。as-of
   replay 先截取当时可见前缀，再校验链，未来损坏记录不能污染过去视图。
6. 来源 correction/retraction/false-claim rate 上升时只允许可靠度下降，初始化不得低于政策
   floor，观察时间、样本量和 policy version 不得倒退或混用；Truth 模型 outcome 必须先可用，
   高置信样本量只能累增，并实现 `NORMAL → DEGRADED → RESTRICTED → RETIRED`，禁止自动恢复。
7. 历史 manifest 校验只声称当前工作树内的固定 SHA 与 artifact-set 自洽；没有受保护远端、
   外部签名或透明日志时，不把它宣传为不可篡改历史。完整 legacy P18 回归是兼容性 gate，不是
   后续 V5 阶段授权；CI 中带时间戳的生成步骤先产出证据，最终 manifest 在其后封存。

## 后果

- P04 可以生成可复现的开发校准证据，但 deterministic fixture 指标不代表真实准确率。
- 校准维度显式绑定 `source class × event type × language × claim type`；样本不足的切片原样
  标记，不拿总体样本冒充切片结论。
- 当前仍为 `DEVELOPMENT`、`NO_PROMOTION`，不会产生订单能力、真实账户连接或 Alpha 声明。

## 回退条件

真实 PIT 标注集若证明候选或校准器失效，只允许通过新版本策略和新 ADR 替换；不得删除历史
预测、重写旧标签可用时间，或让 test/forward 结果倒灌模型选择。
