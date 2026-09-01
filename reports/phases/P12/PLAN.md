# P12 实施计划

## 目标与边界

P12 在 P11 的 `PortfolioProposal → RiskDecision → OrderIntent` 安全链之后建立统一执行服务：只接收
仍在有效期内、已批准且未被撤销的意图，将其量化为某一 Testnet/模拟 venue 的 `OrderCommand`，
维护可重放订单状态、账户流、对账、部分成交、未知状态恢复和账本/Outbox 原子提交。执行层不能
重新决定方向、放大批准增量或绕过风险。

本阶段仅实现模拟账户、录制契约和可选 Binance Testnet。当前没有提供任何 Testnet secret
reference，且项目明确禁止索取或写入明文密码、Cookie、验证码和 API Secret，因此真实 Testnet
网络调用与其验收项按任务书标记 `blocked_external_input`，绝不伪造通过。其余工程契约使用项目自有
确定性模拟器和录制响应完成。OKX、Bybit、Deribit 只建立真实协议能力描述与契约边界，不发送订单。

继续保持 `LIVE_TRADING=false`、`live_trading_locked=true`，拒绝 Live 域名、Live 凭据引用和真实账户。
正式验收按 ADR-0010 统一后置：P12 实现与自动验证完成后仍保持 `in_progress`，不生成
`ACCEPTANCE.md`，不写 `accepted_at_utc`。

## 实施顺序

1. 建立 P12 需求可追踪矩阵，并以 ADR 固化执行输入链、Testnet/模拟边界、未知状态恢复、原子
   Fill/账本/Outbox 和无凭据时的阻塞口径。
2. 实现 `ExecutionVenueAdapter` 协议、严格能力描述和 Binance Testnet/模拟适配器；先用实际已安装
   Nautilus 契约探测决定是否复用，任何不满足的字段或恢复语义记录为兼容结论。
3. 实现 `OrderIntent → OrderCommand` 翻译，验证风险决策、意图时效、部署阶段、instrument 规则、
   client order ID 和批准增量；不得生成 Live 命令。
4. 实现完整内部订单状态机，覆盖 CREATED、RISK_APPROVED、SUBMITTING、SUBMIT_UNKNOWN、
   VENUE_ACCEPTED、PARTIALLY_FILLED、FILLED、CANCEL_REQUESTED、CANCEL_UNKNOWN、CANCELED、
   REJECTED、EXPIRED、RECOVERY_REQUIRED、TERMINAL_RECONCILED；迟到/乱序事件不得回退状态。
5. 实现策略/发布/意图/切片/重试代次关联的确定性 client order ID；同一幂等键只对应一个经济订单，
   未知提交必须先查询 venue，禁止盲重发。
6. 实现账户 WebSocket 序列流、REST 快照、缺口检测、断线重连、周期对账和启动重建；前端连接不
   参与交易连接存活。
7. 实现 partial fill、cancel/fill 与 cancel/replace 竞态、late event、timeout/unknown、未知 venue
   状态和崩溃恢复；无法证明经济事实时进入 `RECOVERY_REQUIRED`/`HALTED`。
8. 实现带 `available_at` 和 TTL 的动态 instrument snapshot，覆盖 tick、step、min/max quantity、
   min notional、订单类型、持仓模式、保证金、交易状态、保护、自成交防护和限频；陈旧或非法精度
   本地失败关闭。
9. 实现 Market with protection、aggressive limit、passive post-only、time-bounded passive、TWAP
   和 reduce-only emergency 的确定性计划；maker/taker 选择显式比较费用、成交概率、逆向选择、
   超时成本、冲击和暴露风险。
10. 实现 `ExecutionGroup`、多腿顺序、裸露名义/时间上限、第二腿失败处置和受批准的紧急对冲；每次
    状态变化重新计算裸露和保证金，不假设跨 venue 原子性。
11. 实现动态限频、撤单/对账/风险优先级、隔离预算、背压与确定性抖动；未知订单不得进入普通重试。
12. 将 Fill、账本分录、执行事件与 Outbox 放入同一数据库事务/幂等边界；模拟持久化故障时不产生
    半写资金事实，重放不重复记账或发布。
13. 实现启动、优雅关闭和崩溃恢复编排；停止新意图、按政策处理挂单、刷新事件与账本、保存快照，
    不擅自平仓。
14. 为 OKX、Bybit、Deribit 建立明确 `CONTRACT_ONLY` capability 和录制契约测试；不存在“成功但
    实际没发送”的假实现。
15. 用属性、契约、集成、Chaos 和定向变异测试覆盖任务书第 15.13 节全部场景；生成模拟 E2E、
    Testnet capability、对账、恢复、原子提交、限频和无 Live 能力证据。
16. 运行全量 pytest、Ruff、Pyright、Python 3.14、mutation、Bandit、秘密、依赖、许可证和前端
    流水线，生成 P12 阶段报告、工件清单并执行一次本地 Git 归档。

## 验证标准

- Adapter 只接收具有匹配 `risk_decision_id` 的有效 Testnet/Paper `OrderCommand`；被风险拒绝、过期、
  放大目标或指向 Live 的输入在 Adapter 前失败。
- 提交超时进入 `SUBMIT_UNKNOWN`；恢复先按 client order ID 查询，任何重放最多产生一个经济订单。
- 订单事件单调、幂等且可重放；部分成交、迟到事件、撤单/成交竞态和新增 venue 状态不产生回退或
  未知资金事实。
- WebSocket 序列缺口通过 REST snapshot/recent orders/recent fills 恢复，账户、订单、Fill 与账本
  对账一致。
- instrument 规则陈旧、精度不合法、账户/持仓模式不匹配或交易暂停时不生成命令。
- 多腿任何时点的裸露名义与持续时间不超过批准上限；第二腿失败进入显式对冲或 Halt 路径。
- Fill、账本和 Outbox 原子；数据库故障、重启和重放不重复成交、记账或发布。
- 本地代码、配置、证据和网络调用均不存在 Live 域名、Live 密钥、真实账户或提现能力。

## 明确非目标

- 不请求 Testnet 明文凭据；没有本地 secret reference 时不执行真实 Testnet 网络验收，也不伪造结果。
- 不实现或启用 Live adapter、Canary、真实资金、真实子账户、提现、风险覆盖或自动 Live 解锁。
- 不把 Testnet/模拟 PnL、成交率或流动性当作策略、Alpha、容量或实盘执行质量证据。
- 不在 P12 启动 P13 的长期 Paper/Shadow 运行，也不以几分钟测试冒充长期稳定性。
- 不做正式 P12 验收；统一验收开始前保持 Live 锁和 `blocked_external_input`/`in_progress` 的真实状态。
