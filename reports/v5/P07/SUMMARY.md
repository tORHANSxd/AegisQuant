# V5-P07 实施摘要

P07 已完成实施并通过阶段验收：Forecast Council 的输入、输出、校准、候选能力、执行门禁、
公平竞技、按 cell 选拔、失败留痕和视觉消融均已落地，并统一受 PIT、内容寻址、时序 cutoff、
同折同样本和 `DEVELOPMENT` 门禁约束。所有数值仍来自确定性 fixture，不声称真实预测准确率、
真实 OOS 增量或 Alpha。

## 已实现

- `MarketStateTensor` 覆盖 5s 至 7d 共 14 档周期，按资产、合约、as-of、特征可得时间和数据集
  Manifest 构造矩形 PIT 输入，并提供可复算内容地址。
- `ForecastEnvelope` 对每档周期输出 q01/q05/q10/q25/q50/q75/q90/q95/q99、涨跌概率、波动率、
  高低区间、MFE/MAE、barrier、tail、流动性、spread/slippage、uncertainty 与 abstain。
- Forecast lineage 绑定模型 revision/capability、Tensor、数据集、逐周期 CalibrationArtifact 和
  `forecast_sha256`；边界重新验证 Pydantic 对象，拒绝 horizon/calibration/capability 拼接。
- 24 候选能力矩阵显式区分 catalog、adapter、依赖、权重、许可和 production eligibility；包含
  基线、TimesFM 2.5、Chronos-2、Moirai-2、Toto 2.0、监督模型、微观结构与可选视觉分支。
- Candidate gate 按实际 capability 重算许可、依赖、权重和 CPU/GPU/RAM/latency 预算；伪造的
  decision、hash 或资源请求 fail closed，目录成员身份本身不构成可运行资格。
- Model Arena 强制相同 split/dataset/calibration/time/sample、唯一 prediction artifact、固定
  evaluation cutoff，并保存 OOM/timeout/invalid-output 等失败。
- Champion 按 asset×horizon×regime 选择，必须超过 baseline 最小门槛；不存在 universal model，
  zero-shot 不可直接晋级，Final Holdout 保持关闭。
- 视觉三方消融使用相同 OOS fold 和预算；无稳定增量时返回 `VISION_NO_OOS_INCREMENT` 并淘汰。
- 新增 10 份 P07 版本化 Schema，并把 P07 证据与 P00-P06 冻结 Manifest 校验接入完整 CI。
- 安全扫描只精确放行模型修订哈希与逐周期校准哈希，普通敏感字段仍受检测；未用路径级排除
  或跳过 CPU 检查掩盖首轮失败。

## 验收结果

- P07 定向测试 `51 passed`。
- 最终完整 CI `66/66` 通过；主环境 `862 passed / 11 warnings`，候选 Python 3.14 环境
  `653 passed / 11 warnings`。
- Ruff format/lint、Pyright strict、Bandit、155 份 Schema drift、Storybook、Next.js build、
  Web E2E 与冻结 P00-P06 Manifest 均通过。
- 安全扫描四项通过，`secret_finding_count=0`，未访问真实账户或 secret store。
- 三项独立只读评审未发现剩余 P0/P1；已修复 gate 重算、budget/request lineage、future cutoff
  与 Forecast 内容地址问题，并固化攻击测试。

## 仍未证明

没有真实公网 PIT 行情、真实外部模型权重、真实训练与校准、Final Holdout、Forward、Paper 或
Shadow 证据；也没有证明基础模型优于简单基线、事件信息有增量、概率校准稳定、尾部召回可靠、
成本后净收益为正或容量可接受。当前 Champion 和视觉淘汰都只是契约夹具结果，不能外推到市场。
