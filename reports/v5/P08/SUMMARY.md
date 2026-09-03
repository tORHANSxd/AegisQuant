# V5-P08 实施摘要

P08 已完成实施并通过阶段验收：市场基线预测、事件条件预测、逐周期事件增量、九臂反事实消融
与固定 horizon 映射退役均已落地，并统一受 PIT、内容寻址、同模型同折同样本和
`DEVELOPMENT` 门禁约束。所有数值仍来自确定性 fixture，不声称真实预测准确率、真实 OOS
事件增量或 Alpha。

## 已实现

- `EventConditionSnapshot` 将 CanonicalEvent、Truth、叙事扩散、市场反映、Surprise、关系与
  directional gate 绑定为可复算的 PIT 事件条件快照。
- `ForecastInputBinding` 与 `EventForecastComparisonLineage` 强制 Market-only 和
  Event-conditioned 使用同一 asset、instrument、horizon、regime、模型 revision、Market State
  Tensor、数据集、校准、fold、时间 cutoff、样本和资源预算。
- `MarketOnlyForecast` 与 `EventConditionedForecast` 复用 P07 概率输出；
  `EventIncrement` 按 horizon 报告预期收益、全部分位数、方向概率、波动、tail、liquidity、
  spread/slippage、uncertainty 和 abstain 差值。
- Rumor 必须保持方向 abstain；市场/事件状态不匹配、未来可得时间、哈希漂移、校准拼接、训练/
  校准/测试样本重叠和 horizon 缺失均被拒绝。
- 九臂消融包含 Market-only、Event-only、Market+Event、Risk-only、Truth/Event/Text permutation
  与 Timestamp/Asset placebo；所有 arm 复用相同 Tensor、模型、校准、fold、样本和预算。
- 消融报告按 asset×horizon×regime 保存主指标、退化阈值、逐臂结果、负控结论和失败原因；
  不进行跨资产汇总式稳定性宣称。
- 生产 `impact.py` 与 `world/fusion.py` 不再持有固定 `HORIZON_SCALE`；旧证据生成器只能显式注入
  synthetic 系数，并绑定系数哈希，固定常量不再拥有生产候选身份。
- 新增 9 份 P08 版本化 Schema；`event-impact-forecast` 升至 v3，历史 v2 保持字节级兼容。
- P08 证据生成器、ADR、CI、Manifest、阶段状态、攻击测试和文档接线已完成；P00-P07 冻结
  Manifest 均保持自洽。

## 验收结果

- P08 定向测试 `31 passed`。
- 最终完整 CI `67/67` 通过；主环境 `893 passed / 11 warnings`，候选 Python 3.14 环境
  `653 passed / 11 warnings`。
- Ruff format/lint、Pyright strict、Bandit、164 份 Schema drift、Storybook、Next.js build、
  三浏览器 Web E2E 与冻结 P00-P07 Manifest 均通过。
- 安全扫描四项通过，`secret_finding_count=0`，未访问真实账户或 secret store。
- 三项独立只读审计未发现未记录的 P0/P1；固定尺度残留已修复，外部 split/permutation/
  prediction 真实性不能由自算哈希证明的边界已记录。
- Truth permutation 未按阈值退化，保存 `TRUTH_PERMUTATION_NOT_DEGRADED`，事件增量门禁未通过。

## 仍未证明

没有真实公网 PIT 行情与事件数据、真实外部模型权重、真实训练与校准、Final Holdout、Forward、
Paper、Shadow 或 Testnet 证据；也没有证明事件信息优于 Market-only、概率覆盖稳定、因果归因成立、
成本后净收益为正或容量可接受。当前预测与消融只验证契约和失败保存，不能外推到真实市场。
