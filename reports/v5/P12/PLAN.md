# V5-P12 执行计划

1. 固定 Truth、Forecast、Cost、Paper、Shadow、Testnet、Risk 七项硬门，禁止加权抵消。
2. 将 P11 Paper/Shadow proof 作为前三项校准与两项 Forward 门的唯一输入。
3. 建立 candidate/strategy/forward-bound 的 real Binance Testnet soak、订单、成交和对账收据。
4. 建立非 loopback 外部告警 acknowledgment、持久收据、不可变锚和受保护时间戳。
5. 用预提交 Ed25519 trust root 验证 Testnet、告警与 TESTNET_ONLY Risk authorization。
6. 七项全 PASS 只生成 `CANARY_REVIEW_READY`，保持资金、Live order 与自动解锁为 false。
7. 对 bundle 中每个来源工件解析真实文件并复算 SHA-256，禁止用路径字符串充当内容承诺。
8. 将 P12 七门与全局 Promotion Gate 分开记录；全局 Data、Truth、Forecast、Economics、Statistics、
   Forward、Risk 未完整评估时必须保持 `NO_PROMOTION`。
9. 生成 Schema、证据、ADR、攻击测试、完整 CI 与冻结 Manifest；如实记录外部硬门阻塞。
