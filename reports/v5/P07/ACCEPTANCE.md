# V5-P07 验收记录

- Evidence Tier: `DEVELOPMENT`
- Alpha Promotion Eligible: `false`
- Decision: `PASS_WITH_RECORDED_NEGATIVE_RESULTS`
- Real-world Forecast Accuracy Claimed: `false`
- Final Holdout Opened: `false`
- Live Trading Locked: `true`

P07 的 14 档预测周期、矩形 Market State Tensor、完整概率预测输出、独立校准工件、24 候选
能力矩阵、候选许可/依赖/权重/预算门禁、等折 OOS Model Arena、按资产×周期×Regime 选拔、
失败保存与视觉消融均已完成。最终完整门禁 `66/66` 通过：主环境 `862 passed / 11 warnings`，
候选 Python 3.14 环境 `653 passed / 11 warnings`，155 份 Schema 工件无漂移，Web E2E stage
通过，安全扫描 `secret_finding_count=0`。P07 定向测试 `51 passed`。

三项独立只读评审覆盖候选门禁伪造、未来 fold、Forecast lineage/content address、阶段治理与
验收完整性。评审发现的 gate 决策输入缺失、实际 capability 未重算、future evaluation cutoff
缺口及 Forecast 内容哈希缺口均已修复并加入攻击测试；`forecast_id` 不等于内容地址这一剩余
P2 风险已记录，实际内容身份由独立 `forecast_sha256` 约束。

首轮完整 CI 暴露了新哈希字段的秘密扫描误报、P11 架构扫描计数漂移，以及 Windows 上一次性
Polars CPU 检查与 Web E2E 瞬态失败。误报改为精确形状白名单，P11 证据已重生成；P15 检查、
三浏览器 E2E 与第二轮完整 CI 均通过。未关闭 Polars CPU 安全检查，也未更新快照掩盖失败。

阶段按记录负结果通过并授权开始 `V5-P08`。该授权不构成真实预测准确率、基础模型有效性、
Alpha Promotion、成本后净收益或实盘授权；外部权重、Final Holdout、订单提交、真实账户连接与
Live trading 继续锁定。
