# P06 阶段总结

P06 以实现提交 `f0733bc70e7210cc41e875a878debc0765c1874a` 为验证对象，完成了任务书
要求的向量化快速筛选、确定性事件回放、历史成本、多级成交、延迟与故障、保证金与强平、
跨场所非原子多腿执行、历史交易规则、指标和标准回测工件。13 项实施任务均已有实现、测试
和机器证据；6 项正式验收条目按项目业主决定继续保持 `in_progress`。

Polars 向量引擎只负责精确的时间对齐和批量筛选，订单、成交、成本、仓位、PnL 与权益最终
全部进入 AegisQuant `Decimal` 领域模型和 P05 权威双重记账。事件引擎支持 bar、trade/quote
和 L2 三档明确精度，不伪造队列位置；故障进入 `UNKNOWN` 并要求 requery，禁止盲目重发。
零成本即时成交时向量/事件结果一致，同一事件与种子重放 5 次只有一个经济事件哈希。

成本 Golden Case 覆盖 maker/taker fee、spread、slippage、impact、funding、borrow interest
和 settlement fee；历史费率与 instrument rule 在精确生效时点切换。保守强平生成显式
reduce-only IOC，并真实经过 P05 账本完成闭仓；cross/isolated 模式以及 SIM/SIM2 跨场所两腿
顺序执行均有直接测试，失败或部分成交时每笔分录仍逐资产平衡。

完整 CI 为 25/25 门通过：Python 3.13.15 为 277 passed，Python 3.14.7 候选契约为
240 passed，Web 单元测试 2 passed、Chromium E2E 1 passed。P06 的 12/12 个关键 mutation
全部被杀死，分数 1.000，高于 0.900 门槛。10,000 事件和 100,000 bar 基准分别约为
116,946 events/s 与 410,405 bars/s；各 5 次稳定性重放均只有一个哈希，Python 峰值内存约
1.41 MiB 与 6.13 MiB。Bandit、秘密扫描与两类依赖审计均通过，秘密发现为 0。

项目业主要求待全部工程完成后再统一验收，因此本阶段没有生成 `ACCEPTANCE.md`，没有写入
`accepted_at_utc` 或权威 `commit_sha`，也没有进入 P07。`LIVE_TRADING` 继续锁定；本阶段未
认证、未访问真实账户、未接收或写入任何明文密码、Cookie、验证码或 API Secret，也未发送
任何订单。
