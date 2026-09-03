# ADR-0034：V5-P11 Paper / Shadow Forward Proof

- 状态：Accepted
- 日期：2026-09-03
- Evidence Tier：`DEVELOPMENT`

## 背景

P10 已把 Forecast、Truth、Price-In、Cost、Portfolio 与独立 Risk 收进同一条非执行决策链，但
确定性 fixture、回测和加速稳定性测试都不能证明模型在真实时间流中的表现。主计划要求 P11 提供
continuous forward data、无未来修正、Truth/Forecast/Cost 的 predicted-vs-realized 校准、事件增量
归因、事故日志和 restart/recovery；不得使用回测替代 Forward。Paper 建议至少 `30 calendar days`，
独立事件样本不足时必须 `EXTEND_PAPER`，不得降低门槛。

## 决策

1. Prediction 与 Realization 分时记录。预测载荷在 outcome 可用前生成独立 SHA-256，revision 固定为
   0，禁止 correction 链；source availability 晚于 decision time 时 fail closed。
2. Paper 与 Shadow 各自产生带严格 sequence、previous hash 和 source availability 的 heartbeat 链；
   预提交策略把最大 gap 限制在 3600 秒以内，断档不能被后补记录掩盖。
3. `ForwardProofPolicy` 在 run 开始前锁定，`minimum_calendar_days` 在类型层不得低于 30；独立事件数
   门槛必须带理由，运行后不得为过关而下调。
4. 从原始样本重算 Truth Brier/校准差、Forecast MAE/方向准确率、Cost MAE/低估率、事件增量
   MAE/方向准确率。调用方提交的 pass 布尔值不受信任。
5. Incident log 覆盖整个 session，restart receipt 必须绑定 restart incident、checkpoint、前后链头、
   durable sequence、gap 与 duplicate 数；缺记录、未解决、数据丢失或未来修订一律 fail closed。
6. 只有非 time-compressed 的 wall-clock run 才可标记 `PAPER_FORWARD` 或 `SHADOW_FORWARD`。
   DEVELOPMENT fixture 只能得到 `EXTEND_PAPER / NO_PROMOTION`。
7. Paper/Shadow 必须同 pair、同窗口、同预提交策略和同预测集合。两者都 PASS 只授权进入 P12
   Testnet readiness；P11 永远不能生成 `CANARY_REVIEW_READY`，也不能解锁 live。

## 当前证据解释

当前仓库仅提供确定性 DEVELOPMENT contract fixture，用于证明门禁会拒绝回测替代、短窗口、事件
不足、断档、未来数据、校准失败和拼接攻击。真实观察日数为 0，不能把测试中的 30 日时间戳当作
时间已经流逝。阶段实现可以按记录负结果验收，但 Promotion 必须保持 `NO_PROMOTION`，后续真实
Paper/Shadow 采集必须延长到门槛满足。

## 后果

- 好处：Forward 证据有统一、可重算、可恢复的机器契约，fixture 无法冒充真实时钟证据。
- 代价：当前不能宣称 P11 Forward PASS；至少 30 个真实日历日和足够独立事件无法靠一次 CI 获得。
- 剩余风险：结构化字段和内容哈希仍不证明外部时钟、数据源或风险服务签发真实性，P12 还需签名
  授权收据、外部告警、真实 Binance Testnet、soak 与 reconciliation。
