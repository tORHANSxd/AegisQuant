# V5-P06 实施摘要

P06 已完成实施并通过阶段验收：事件响应样本、历史状态匹配、matched event study、
synthetic control、doubly robust AIPW、placebo 与因果诊断均已落地，并统一受 PIT、内容寻址、
固定诊断策略和证据等级门禁约束。所有数值仍来自确定性 `DEVELOPMENT` fixture，不声称真实因果
效应、预测准确率或 Alpha。

## 已实现

- `EventResponseDataset` 绑定 CanonicalEvent 身份、revision、Truth、来源质量、novelty、
  reflection、actual/expected/Surprise、regime、盘前协变量与叙事，并覆盖 5m/30m/4h/1d/7d
  收益、波动、流动性、尾部、MFE 和 MAE。
- 数据集按行和整体内容寻址，拒绝 future event/feature/label/outcome、同 revision 异身份、
  Surprise 拼接以及不完整 7d outcome；所有传入 Pydantic 对象在边界重新验证。
- 历史状态匹配采用确定性标准化最近邻与 caliper，结果绑定 treated、matching spec、as-of 和
  control state hash；matched DID 只报告点估计，不伪造单事件标准误或置信区间。
- Synthetic control 使用 simplex 约束权重和 pre-treatment 路径，拒绝未来 donor 决策、特征和
  outcome；pre-fit 不合格时因果声明 fail closed。
- AIPW 使用预先计算的 PIT nuisance predictions，并绑定 nuisance model hash、training cutoff、
  feature snapshot hash 与 availability；输入同时要求 treated/control overlap。
- pre-fit、pre-trend、covariate balance、propensity overlap、event timestamp placebo、asset
  placebo 与 treatment permutation 均保存原始可复算输入，拒绝阈值、结果或 policy 伪造。
- `CausalEffectEstimate` 同时绑定诊断结果和 evidence tier；`DEVELOPMENT` 即使诊断通过也只能
  `NO_PROMOTION`，订单提交关闭且 Live trading 锁定。
- 新增 19 份 P06 版本化 Schema，并把 P06 证据与 P00-P05 冻结 Manifest 校验接入完整 CI。

## 验收结果

- P06 定向测试 `35 passed`，相关历史兼容集 `123 passed`。
- 最终完整 CI `65/65` 通过；主环境 `811 passed / 11 warnings`，候选 Python 3.14 环境
  `653 passed / 11 warnings`，Web E2E stage 通过。
- Ruff format/lint、Pyright strict、Bandit、Schema drift、Storybook、Next.js build 与冻结
  P00-P05 Manifest 均通过。
- 安全扫描全部通过，`secret_finding_count=0`，未访问真实账户或 secret store。
- 三项独立只读评审发现并促成修复匹配结果跨 treated/spec/control 拼接、单事件伪标准误、
  单组 propensity overlap、未来 donor 泄漏、AIPW nuisance lineage 缺口与历史 Manifest/状态
  未交叉绑定；攻击测试与治理检查已固化。

## 仍未证明

没有真实 PIT 事件语料、真实 donor pool、真实 propensity/nuisance 训练、未观测混杂排除、真实
因果效应、OOS 预测增量、成本后净收益或 forward trading 证据。当前诊断通过只证明构造样本可被
重算且坏设计会被门禁挡住，不证明市场中的识别假设成立。
