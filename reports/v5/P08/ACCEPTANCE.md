# V5-P08 验收记录

- Evidence Tier: `DEVELOPMENT`
- Alpha Promotion Eligible: `false`
- Decision: `PASS_WITH_RECORDED_NEGATIVE_RESULTS`
- Real-world Forecast Accuracy Claimed: `false`
- Final Holdout Opened: `false`
- Live Trading Locked: `true`

P08 已完成 `MarketOnlyForecast`、`EventConditionedForecast` 与逐周期 `EventIncrement`，并将
Truth、事件、文本、时间戳及资产反事实与 Market-only、Event-only、Market+Event、Risk-only
四类基准纳入同一 PIT Tensor、模型、校准、fold、样本和预算约束。最终完整门禁 `67/67`
通过：主环境 `893 passed / 11 warnings`，候选 Python 3.14 环境 `653 passed / 11 warnings`，
164 份 Schema 工件无漂移，Web E2E stage 通过，安全扫描 `secret_finding_count=0`。P08
定向测试 `31 passed`。

三项独立只读审计覆盖固定 horizon 收益映射、PIT/lineage/permutation 攻击面和阶段接线。
生产源码中的固定 `HORIZON_SCALE` 已移除，旧证据只能由调用方显式注入 synthetic 系数；
Rumor 不能产生方向事件 Alpha，比较对象必须 exact lineage join，缺臂、跨折拼接、样本重叠、
未来 cutoff、伪造内容哈希或不完整 horizon 均 fail closed。

独立安全审计同时确认：单独的内容哈希只能证明 payload 自洽，不能独立证明外部 split、置换计划
或 prediction artifact 的真实性。该限制已写入 `RISKS.md`，本阶段 Manifest 是工作树信任锚，
未将其夸大为签名来源、透明日志或真实数据证明。

确定性九臂消融中 Truth permutation 未达到最小退化阈值，明确保存
`TRUTH_PERMUTATION_NOT_DEGRADED`；因此事件增量门禁未通过，阶段决策只能是记录负结果的契约
验收，不能声称事件信息存在可交易增量。任何非零 fixture `EventIncrement` 也不得外推到真实市场。

完整 CI 初轮暴露了下游 P11/P15 证据漂移、秘密扫描对历史 SHA 字段的误报及浏览器快照中展示
短哈希变化。相关生成证据已重算，秘密扫描仅对精确历史 SHA 字段做形状豁免，六张浏览器基线
只更新了已核验的哈希文本；随后三浏览器 E2E 与最终完整 CI 均通过。

阶段按记录负结果通过并授权开始 `V5-P09`。该授权不构成真实预测准确率、事件 Alpha、成本后
净收益、Paper/Shadow/Forward、Testnet/Canary 或实盘授权；外部权重、Final Holdout、订单提交、
真实账户连接与 Live trading 继续锁定。
