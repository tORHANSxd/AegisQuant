# V5-P10 实施摘要

P10 已完成实施并通过阶段验收：Forecast、Truth、Price-In、11 项成本、Net Edge、Portfolio 与
独立 Risk 被收进同一条可重算、无旁路的非执行决策链。输出只能是研究型 Directional Alpha、
保护型 Risk Overlay 或第一类 NO_TRADE，三者互斥。全部证据仍为 `DEVELOPMENT`，不声明真实
准确率、Alpha、成本后收益或可交易性。

## 已实现

- `ExecutionCostModelV2` 显式覆盖 11 个成本分量、BACKTEST/PAPER/LIVE scope、TCA 校准状态与
  置信度；Maker 队列支持保守模式和绑定六项输入的 replay 模式。
- Forecast 与 Cost 使用概率场景分布；Maker 排队概率进入成交机会调整后的 gross edge，场景数量
  上限为 4096，概率和、期望值与内容哈希均可重算。
- Net Edge 同时检查 expected edge、正收益概率、LCB、edge/cost ratio、Truth、Price-In、
  uncertainty、OOD、data quality、event increment、Portfolio 与 Risk。
- Bootstrap/OOS 阈值按 asset×horizon×sleeve 显式版本化；OOS 阈值必须绑定内容寻址证据。
- Forecast 内容派生 `SignalId`，Portfolio leg 与独立 Risk target 必须精确匹配资产、instrument、
  strategy、account、当前权重和目标权重；边界重验载荷以阻止 `model_construct` 伪造。
- 严重事件只有在极高 Truth、novelty、未 price-in、事件增量和成本后净边均过门时才允许研究型
  Directional Alpha；中等 Truth 的极端事件只能触发 REDUCE_ONLY/HALTED 保护性 Overlay。
- 新增 14 份 P10 顶层版本化 Schema，注册表总数为 188；证据、ADR、CI、Manifest 与攻击测试
  已接线，P00-P09 冻结 Manifest 保持自洽。

## 验收结果

- P10 架构边界加定向测试 `40 passed`。
- 最终完整 CI `69/69` 通过；主环境 `969 passed / 11 warnings`，候选 Python 3.14 环境
  `653 passed / 11 warnings`。
- Ruff format/lint、Pyright strict、Bandit、188 份 Schema drift、安全、Storybook、Next.js build、
  Web E2E 与冻结 P00-P09 Manifest 全部通过。
- Web 单元测试 `19 passed`；安全扫描四项通过，`secret_finding_count=0`，没有真实账户或 secret
  store 访问。
- 独立攻击复核发现的目标拼接、队列经济性、场景上界和构造绕过已修复；风险服务签发真实性作为
  `V5-RISK-020` 留待 P12 的签名授权收据解决。

## 仍未证明

没有真实公网 PIT OOS、连续 Forward、真实 TCA、Paper、Shadow、Testnet 或 Live 数据；离散场景
不代表真实联合分布，Bootstrap 阈值不是 Alpha 参数，内容哈希不证明外部工件或风险服务签发真实。
Final Holdout 未打开，Alpha promotion 不合格，订单提交和 Live trading 保持关闭。P11 必须建立
连续 Paper/Shadow Forward 与 predicted-vs-realized 监控，而不是拿 DEVELOPMENT fixture 冒充战绩。
