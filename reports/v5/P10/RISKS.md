# V5-P10 风险台账

- `V5-RISK-017`：场景概率与真实联合分布不一致。处置：P10 仅作 DEVELOPMENT 契约验证；
  P11/P12 必须用 PIT OOS/Forward 数据重估。
- `V5-RISK-016`：成本模型的 TCA 置信度来自确定性 fixture。处置：失准必须折减 Net Edge
  概率，P11 建立 predicted-vs-realized 连续监控。
- `V5-RISK-018`：Bootstrap 阈值被误当作永久 Alpha 参数。处置：阈值无默认值、按 cell
  版本化，OOS 来源必须带证据哈希。
- `V5-RISK-019`：Risk Overlay 被偷换成方向交易。处置：独立互斥类型、仅接受
  REDUCE_ONLY/HALTED 风险裁决，方向 Alpha 字段恒为 false。
- `V5-RISK-020`：内容哈希与结构校验不能证明外部工件真实性，P10 仍信任风险子系统产生的
  `RiskDecision`。处置：保留负结果；P12 执行边界必须绑定签名策略、快照、告警和不可变审计收据。
