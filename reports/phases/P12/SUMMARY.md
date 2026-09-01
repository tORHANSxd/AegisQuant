# P12 实施总结

P12 已完成 Testnet/模拟执行领域层、订单恢复、账户对账、执行算法、多腿风险约束和原子资金事实实现。
执行链严格绑定 P11 的有效 `RiskDecision → OrderIntent`，且只允许 `SIMULATED` 或显式 `TESTNET`；
`LIVE_TRADING` 继续锁定，仓库不存在 Live adapter、生产域名、真实账户或提现能力。

## 已交付

- `OrderIntent → SubmitOrderCommand` 的风险、时效、规则、数量和内容哈希门禁，以及包含策略、发布、
  意图、切片和重试代次的确定性 client order ID。
- 14 态可重放订单状态机；重复、迟到、乱序、序列缺口、部分成交、撤单竞态和未知 venue 状态均
  单调处理，无法证明的事实进入恢复态。
- 证据优先的提交/撤单恢复：超时不等于失败，恢复先查询 open/recent orders 与 fills；同一经济
  幂等键跨重试代次也最多创建一个经济订单。
- 账户序列流、REST 快照、缺口检测、重连和订单/Fill 双向对账；前端连接状态不控制交易连接。
- 带有效期的动态 instrument 规则、maker/taker 成本选择、受保护限价、限时被动、TWAP、
  reduce-only、多腿裸露上限和安全优先限频队列。
- PostgreSQL 中 Fill、账本、领域事件和 Outbox 的同事务提交；故障注入证明回滚不留下半写资金
  事实，提交前权威内存账本不前移。
- 启动对账、运行、quiesce、停止和崩溃恢复生命周期；OKX、Bybit、Deribit 仅提供会拒绝发送的
  `CONTRACT_ONLY` 边界，不用恒定成功假装已接入。

## 验证状态

完整 CI 37/37 阶段通过；Python 3.13 全量测试 541/541、Python 3.14.7 隔离候选契约 502/502
通过，严格 Pyright 与 Ruff 均为 0 问题。15/15 个关键变异全部被杀死。真实一次性 PostgreSQL 的
正常原子提交与故障回滚均通过。Bandit finding 与秘密命中均为 0，Python/JavaScript 依赖审计、
SBOM、许可证清单、前端 lint、类型检查、单测、生产构建和 Playwright E2E 全部通过。

证据收口保留三类预跑处置：安全扫描曾把旧等待凭据状态名和审计字段误判为秘密；历史 P07–P11
测试漏接 P12 共享报告；首遍 Python 3.14 候选又被本地 `compileall`
写入人工导入夹具的 `.pyc` 污染。前两项通过精确命名和历史阶段集合修正，第三项仅移走临时缓存，
没有放宽安全导入规则；最终全量结果均通过，详见 `TEST_RESULTS.json`。

## Testnet 与验收边界

当前未收到任何本地 Testnet credential reference。依照任务书和 ADR-0017，真实 Binance Testnet
提交、部分成交、撤单、重连与重启验收行 `P12-A01` 保持 `blocked_external_input`；未读取环境变量、
未访问秘密存储、未实例化 Nautilus 执行客户端、未发网络请求，也未连接任何账户。模拟 E2E 只证明
领域契约和故障恢复，不证明交易所连通性、成交质量、策略收益或实盘可用性。

正式验收按 ADR-0010 统一后置。P12 保持 `in_progress`，不生成 `ACCEPTANCE.md`，不写
`accepted_at_utc`，实现提交为 `7e9469d77aae32753bf665f9b2b598c64b455ea4`。
