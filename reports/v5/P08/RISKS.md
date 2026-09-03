# V5-P08 风险

1. 事件条件预测的差异仍可能来自模型、校准、样本或预算差异，必须做 exact lineage join。
2. 事后 Truth、CanonicalEvent revision、市场反应或 Surprise 回填会制造严重 hindsight leakage。
3. Truth/Event permutation 不退化说明对应层没有增量，不能靠主模型 loss 较低遮过去。
4. Timestamp/Asset/Text placebo 不退化可能意味着 beta、标签泄漏或事件信息并非因果来源。
5. 单一 horizon 或极端事件的改善不能外推到跨时间、跨资产稳定性。
6. Primary loss 改善不等于成本后净收益，P10 前不得据此进入组合或风险路径。
7. Confirmed 只代表事件门禁的一部分；Rumor directional alpha 仍必须禁用。
8. 当前 fixture 不含真实公网数据、真实训练或真实校准，不证明事件增量有效。
9. 工作树内容寻址不替代签名远端或透明日志。
10. 单独一个 SHA-256 只能证明 payload 自洽，不能证明外部 split、置换计划或 prediction 的真实性；
    阶段 Manifest 是当前信任锚，后续阶段仍需签名来源与可重放数据集核验。
