# ADR-0035：V5-P12 Testnet / Canary Readiness

- 状态：Accepted
- 日期：2026-09-03
- Evidence Tier：`DEVELOPMENT`

## 背景

P11 建立了 Paper/Shadow Forward 证明契约，但当前真实观察日数为 0。旧 P12 的 Binance 适配器是
无网络模拟器，旧 P16 外部告警只有 loopback 收包，旧 P18 结论为 `NO_GO`。这些资产可复用其订单
恢复、对账和硬门结构，不能冒充 real Binance Testnet、外部告警或 V5 Forward 证据。

主计划规定 Truth calibration、Forecast calibration、Cost calibration、Paper、Shadow、Testnet、
Risk 七项必须全部 PASS，才可生成 `CANARY_REVIEW_READY`；任一 hard gate 失败即
`NO_PROMOTION`，且 readiness 仍不得自动解锁 Live。

## 决策

1. 七项门按固定顺序、固定数量重算，状态只能为 `PASS`、`FAIL` 或
   `BLOCKED_EXTERNAL_INPUT`；禁止 soft gate 和加权平均。
2. Truth、Forecast 与 Cost 门直接消费 P11 Paper/Shadow proof。只要来源是 DEVELOPMENT、压缩时间
   或未达到真实 Forward PASS，三项校准和 Paper/Shadow 门均不得通过。
3. Binance Testnet 证据必须绑定 candidate、strategy、P11 forward pair/proof、仅 Testnet 的账户
   scope、credential reference、真实私有网络请求、订单/成交计数和完整 reconciliation。模拟器、
   原始凭据、Live 域名、Live 账户或 withdrawal 均不能进入通过路径。
4. Testnet soak、最少 accepted/terminal order 和 fill 数由运行前哈希锁定的 policy 控制。当前
   DEVELOPMENT bootstrap 取 24 小时、3 个 accepted、3 个 terminal、2 个 fill；这只是合同阈值，
   不是生产样本功效结论，观察后不得为过关下调。
5. 外部告警必须是非 loopback HTTPS 投递，所有频道均收到 2xx acknowledgment，并具有持久收据、
   不可变审计锚和由独立预提交时间戳 authority 签发的受保护时间戳；loopback contract receiver
   只能算 DEVELOPMENT。
6. Testnet、告警、Risk 三类证据分别由 policy 中预提交的 Ed25519 attestor trust root 验签，并由
   独立 timestamp trust root 验证时间。Risk receipt 必须
   绑定 P12 policy、P10 integrated decision、风险快照、Testnet run、reconciliation 和 alert，且
   scope 固定为 `TESTNET_ONLY`。
7. 七门全过最多产生 `CANARY_REVIEW_READY` 和 `REQUEST_MANUAL_CANARY_REVIEW`。资金授权、用户批准、
   manual Live unlock、Live order capability 与 Final Holdout 均保持 false；Live lock 永远为 true。
8. P12 七门不是全局 Promotion Gate 的替身。Data、Truth、Forecast、Economics、Statistics、Forward、
   Risk 全维度证据必须另行完整评估；任一 hard fail 或未评估维度均输出 `NO_PROMOTION`。
9. P12 bundle 中的来源工件记录相对路径与实际文件内容 SHA-256；生成阶段和验收阶段都逐个解析、
   复算，禁止以路径字符串的哈希冒充工件承诺。

## 当前证据解释

仓库当前没有真实 Paper/Shadow、Binance Testnet、credential reference、网络订单/成交、外部告警或
Testnet Risk authorization。P12 评估因此为 `0 PASS / 0 FAIL / 7 BLOCKED_EXTERNAL_INPUT`，结论
`NO_PROMOTION / EXTEND_PAPER`。测试里的全通过对象只验证决策真值表和签名/拼接防线，不是观察证据。
全局 Promotion Gate 因 Data、Economics、Statistics 与 Forward 证据不完整而未执行，结论仍是
`NO_PROMOTION`，不能拿局部七门的合同完整性偷换成 Alpha 有效性。说白了，门框装得再结实，也不能
证明屋里真有金矿。

## 后果

- 好处：模拟器、loopback 告警、伪造哈希、伪造时间戳、错签、跨 candidate/strategy/run 拼接和
  单门失败加权抵消都不能制造 readiness。
- 代价：没有外部凭据和真实时间经过，就不可能把 P12 跑成 PASS；这正是硬门，不是缺陷。
- 剩余风险：当前 trusted attestor 是 DEVELOPMENT fixture key，真实 attestor 的身份、密钥托管、
  吊销和透明日志尚未建立；真实 Testnet 样本门槛也缺乏功效研究。
