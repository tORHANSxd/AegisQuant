# V5-P09 实施摘要

P09 已完成实施并通过阶段验收：Forecast Council 现在拥有内容寻址的评审上下文、只读
Meta-Reasoner、独立 Skeptic、可重算分歧、统计动态 stacking、PIT/OOD regime router，以及按
asset×horizon×regime 维护的自适应分布尺度校准。所有证据仍为 `DEVELOPMENT`，不声称真实预测
准确率、区间覆盖、成本后净收益或可交易 Alpha。

## 已实现

- `ReasoningContext` 完整绑定 Truth、证据图、事件、预测、regime、可靠度、校准、OOD、price-in、
  成本、组合与风险工件，并预提交 Meta-Reasoner/Skeptic 各自不同的 prompt/model revision。
- 两条 LLM 路径只能产出结构化研究建议，不能下单；Skeptic 严重发现和 Meta abstain 只能收紧
  治理结果。
- Council disagreement 从候选 expected return 重算，方向冲突和区间超限均可触发 abstain。
- `StatisticalWeightProposal` 只接受 validation/calibration/forward 白名单，至少需要前两者且禁止
  Final Holdout；forward 在真实 PIT 证据出现前保持缺席。
- 动态权重复用 capped stacking 与 maximum-step smoothing，并增加 simplex cap 可行性、最终 cap
  和实际步长复核。
- Regime router 对未来数据、OOD、UNKNOWN、低数据质量、不确定 Truth、低可靠度及跨 cell/model
  拼接 fail closed。
- distribution-aware conformal 使用预测区间 scale 归一化 nonconformity；新预测必须提供正的 base
  scale。滚动 coverage 从结果重算并输出 NONE/RECALIBRATE/DEGRADE/ABSTAIN。
- 两类哈希集合使用不可变绑定 tuple，边界重新验证 `model_construct`/`model_copy` 伪造，避免浅冻结
  字典被原地修改。
- 新增 10 份 P09 顶层版本化 Schema，注册表总数为 174；阶段证据、ADR、CI、Manifest、state 与
  攻击测试已接线，P00-P08 冻结 Manifest 均保持自洽。

## 验收结果

- P09 定向测试 `40 passed`。
- 最终完整 CI `68/68` 通过；主环境 `933 passed / 11 warnings`，候选 Python 3.14 环境
  `653 passed / 11 warnings`。
- Ruff format/lint、Pyright strict、Bandit、174 份 Schema drift、Storybook、Next.js build、Web E2E
  与冻结 P00-P08 Manifest 全部通过。
- 安全扫描四项通过，`secret_finding_count=0`，未访问真实账户或 secret store。
- 三项独立只读复核提出的高/中风险缺口已修复或按主计划语义澄清；P09 报告、CI 和 Manifest 在
  阶段冻结时收口。

## 仍未证明

没有真实公网 PIT 数据、真实训练/校准、真实 OOS 或 Forward 权重证据、Final Holdout、Paper、
Shadow 或 Testnet。动态权重未证明优于简单平均，distribution-aware 校准未证明真实覆盖，模型与
prompt hash 不证明供应商或训练语料层面的独立，内容哈希不证明外部工件真实性。最关键的是 P09
governance 尚未成为执行授权输入；P10 必须把 Forecast、Truth、Price-In、Cost、Portfolio 与独立
Risk 绑定成无旁路链路，并把 `NO_TRADE` 作为一等结果。
