# ADR-0017：P12 Testnet 执行、恢复与原子资金事实政策

- 状态：Accepted for implementation
- 日期：2026-09-02
- 决策范围：P12

## 背景

P12 必须把风险批准的 `OrderIntent` 安全地转换为 Testnet/模拟订单命令，处理未知提交、账户流、
部分成交、竞态、动态规则、多腿裸露、限频、崩溃恢复和 Fill/账本/Outbox 原子性。执行层一旦把
“超时”等同于“失败”或允许同一经济意图盲重发，就可能制造重复订单；若 Fill、账本和 Outbox
分开提交，则会产生无法解释的资金事实。

项目当前未配置 Binance Testnet secret reference。任务书要求无凭据时可以完成模拟与契约实现，
但真实 Testnet 验收必须标记阻塞，不得伪造通过。项目也禁止索取或保存任何明文密码、Cookie、
验证码或 API Secret。

已安装 `nautilus-trader==1.231.0`。实际 Python 契约暴露 `BinanceExecClientConfig`、
`BinanceLiveExecClientFactory`、`BinanceEnvironment.TESTNET/DEMO/LIVE` 和 Spot/Futures submit、modify、
cancel、order status、fill report、connect/disconnect 方法；该版本使用 `account_type`、`base_url_ws`、
`base_url_ws_stream` 等字段，且 `environment=None` 会解析为 Live。Nautilus 官方 latest 文档已经使用
更新后的产品命名和更多配置项，并明确 Testnet 是 legacy 环境、Futures 新模拟路径优先 Demo，且
超时/网络失败/未知状态不能盲重试：

- <https://nautilustrader.io/docs/latest/integrations/binance/>
- <https://nautilustrader.io/docs/python-api-latest/adapters/binance.html>

因此最新文档不能替代本项目固定版本的实际导入和签名契约测试。

## 决策

1. P12 的权威边界是项目自有 `ExecutionVenueAdapter` 协议和领域状态机。Nautilus 仅作为已验证的
   候选底层客户端；由于它不直接提供本项目要求的 RiskDecision 绑定、经济幂等、原子账本/Outbox
   和恢复案例语义，P12 使用领域层后的原生执行编排，而不是让框架对象绕过领域边界。
2. Nautilus 兼容报告必须来自固定版本 `1.231.0` 的实际导入、类字段、方法和 Testnet URL 解析；
   不实例化执行客户端、不读取环境变量、不访问秘密存储、不发网络请求。任何升级先运行契约测试并
   新建 ADR。
3. 所有可发送 Adapter 配置必须显式为 `TESTNET`；`None`、`LIVE`、Live 域名、Live 凭据引用、真实
   账户和提现能力均失败关闭。模拟 Adapter 使用 `SIMULATED`，不执行网络 I/O。
4. 当前真实 Testnet capability 状态为 `AWAITING_CREDENTIAL_REFERENCE`，对应验收行
   `blocked_external_input`。仅记录预期的 secret reference 名称是否存在，绝不记录值；未提供时
   不请求、不探测、不调用 Testnet。
5. 唯一执行链为：有效且批准的 `OrderIntent` → 动态规则量化 → `OrderCommand` → 订单状态机 →
   Adapter。执行层不得改变策略方向，不得超过批准数量，不得绕过 `risk_decision_id`。
6. 请求超时进入 `SUBMIT_UNKNOWN`。恢复必须先按 client order ID 查询 open/recent orders 与 recent
   fills；确认不存在后才允许提高 retry generation。同一幂等键永远只对应一个经济订单。
7. 内部订单状态单调、幂等、可重放。迟到/乱序事件可补充证据但不能回退状态；未知 venue 枚举进入
   `RECOVERY_REQUIRED`，不能猜测成 rejected/canceled/filled。
8. instrument snapshot 必须带版本、`available_at` 与有效期；规则陈旧、精度非法、交易暂停、持仓
   模式不符或订单类型不支持时在本地拒绝。
9. Fill、账本分录、执行事件和 Outbox 在一个数据库事务边界内持久化。权威内存账本仅在数据库提交
   成功后应用同一确定性 Fill；失败时数据库和内存均保持原状态，重放按 Fill/idempotency key 去重。
10. 多腿交易不假定原子成交。每次腿状态变化重新计算裸露；超出名义或时间上限时只允许预批准的
    reduce-only 对冲或进入 HALTED。
11. 正式验收继续按 ADR-0010 后置，不生成 P12 `ACCEPTANCE.md`。真实 Testnet 阻塞不是豁免，也
    不能用模拟成交替代。

## 后果

- 好处：框架版本变化不会改变安全语义；超时不会重复经济订单；资金事实可事务化重放；缺少 Testnet
  凭据时结果诚实且仍可完成绝大多数工程验证。
- 代价：需要维护项目自有执行状态机和 Nautilus 兼容层；真实 Testnet 提交/撤单/重连证据必须等
  用户未来只配置本地 secret reference 后另行运行。
- 禁止：直接使用 Nautilus 默认 Live 环境、从对话或仓库读取凭据、把 Testnet/模拟 PnL 当成实盘
  证据、在未知提交时普通重试、用空方法或恒定成功返回值冒充 OKX/Bybit/Deribit 适配器。
