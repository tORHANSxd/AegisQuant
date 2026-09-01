# ADR-0009：P05 权威会计、FIFO、估值与签名策略

- 状态：Accepted for P05 implementation
- 日期：2026-09-01

## 背景

P05 必须把成交、费用、资金费率、借贷、划转、估值和对账统一到一个可重放的资金事实
系统。既有 P01 只固化 `JournalEntry` 与 `PositionLot` 不变量，并非完整会计引擎。

## 决定

1. 账本按原生资产逐币种平衡；每个 `JournalEntry` 的同一资产借方等于贷方，禁止用隐式
   汇率把不同资产相互抵消。
2. 头寸成本采用 FIFO。FIFO 便于逐 Fill 审计、重放和更正；平均成本不作为 P05 权威政策，
   若未来新增必须通过 superseding ADR 和独立 Golden Case。
3. 现货资产、成本基础和清算腿分开入账；衍生品以 memo position cost/clearing 腿记录
   lot 基础，已实现 PnL 只在关闭数量时进入现金与收益/费用科目。
4. 正向 PnL 为 `signed_contracts * multiplier * (exit - entry)`；逆向 PnL 为
   `signed_contracts * multiplier * (1 / entry - 1 / exit)`，结算资产与单位必须来自已版本化
   instrument 契约。所有金额只接受有限 `Decimal`。
5. 未实现 PnL 是估值投影，不写入永久收益科目。估值优先级固定为 `MARK -> MID -> LAST ->
   INDEX`，实际使用的来源、价格、时间和策略版本进入快照。
6. 权益按报告资产计算时必须提供版本化 FX/估值价格；缺少价格时失败关闭，不猜汇率。
7. Fill ID 与幂等键同时唯一。完全相同的重放返回既有结果；任一键复用到不同内容均为
   致命冲突。
8. 对账只能生成差异、状态和建议动作，禁止自动改账。调整必须是显式、带证据和审批引用
   的 `ReconciliationAdjustment`。
9. 每日快照使用调用方注入的 Ed25519 signer。测试密钥只在内存生成；仓库和报告只保留
   public key、签名和哈希，不保存私钥。
10. mutation gate 使用仓库内确定性源码变异运行器，不增加依赖；账本平衡、FIFO、PnL、
    幂等和对账关键变异分数门槛为 90%。
11. `borrow_interest` 在领域模型中以非负费用金额保存，并在 PnL 守恒式中扣减；这与把借贷
    利息记为带符号负现金流后再相加经济等价，但前者能避免费用正负号在 API 边界重复翻转。

## 外部项目对照

按项目业主建议只读核对 [HKUDS/AI-Trader](https://github.com/HKUDS/AI-Trader)。其 Agent 接入、
Paper Trading、后台结算任务和 PostgreSQL/SQLite 双后端思路可作为后续实验与产品层参考；但
[费用配置](https://github.com/HKUDS/AI-Trader/blob/main/service/server/fees.py) 使用浮点常量，且该项目
定位为 Agent-Native 平台，并未提供本任务书要求的原生资产双重记账、FIFO、哈希重建和强制对账
契约。因此 P05 不复制其会计实现、不引入其依赖，也不连接其服务；本 ADR 与任务书仍是权威边界。

## 后果

- 原生资产账本与报告资产估值明确分层，避免把汇率损益偷偷塞进成交事实。
- FIFO 会产生更多 lot，但审计、回放和局部更正更直接。
- 不提供凭据、不访问账户、不下单；模拟 venue snapshot 是 P05 唯一外部账户证据。
- 正式验收按项目业主要求延后；实现测试可以通过，但 P05 状态保持 `in_progress`。
