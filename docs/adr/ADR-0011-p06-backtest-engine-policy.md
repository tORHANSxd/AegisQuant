# ADR-0011：P06 双回测引擎、精度与模拟政策

- 状态：Accepted for P06 implementation
- 日期：2026-09-01

## 背景

P06 需要兼顾大范围向量研究和高保真事件回放。官方 PyPI 在 2026-09-01 显示
NautilusTrader `1.231.0` 为最新稳定版，本项目锁文件与本机契约同样为 `1.231.0`；官方文档
说明其回测支持确定性事件流、L1/L2 撮合和固定随机种子。但 Windows wheel 使用 64 位标准
精度，最多 9 位小数，且项目仍提示版本间可能发生破坏性 API 变化。AegisQuant 的权威金额与
账本不能降精度，也不能把第三方框架对象当作领域事实。

## 决定

1. 向量引擎使用 Polars 加 AegisQuant `Decimal` 领域边界；Polars 只承载批量时间序列计算，
   权威订单、成交、成本和 PnL 在输出边界恢复为精确十进制模型。
2. 事件引擎实现 AegisQuant 自有 `EventBacktestEngine`，直接连接 P05 `LedgerEngine`。锁定的
   NautilusTrader `1.231.0` 作为事件排序、撮合语义和确定性回放的契约交叉验证组件，而不是
   权威账本或精度来源。
3. 零成本一致性场景使用预先可用的目标仓位指令和相同执行时点，禁止用同一根 bar 的未来
   信息成交。两个引擎必须输出相同成交、最终仓位、现金与权益。
4. 成交精度分为 `BAR_CONSERVATIVE`、`TRADE_QUOTE`、`L2_DEPTH`。没有队列位置数据时禁止
   宣称 queue-aware 精确性；结果必须携带精度等级与假设。
5. 成本政策按有效时间、场所、产品和来源版本化，分别记录 maker/taker fee、spread、
   slippage、impact、funding、borrow interest 与结算费用，禁止一个全局固定 bps 覆盖市场。
6. 随机过程必须显式提供种子。相同数据、配置、代码和种子必须产生相同经济事件哈希；历史
   市场簿不可因模拟成交而被修改。
7. 历史 instrument rule 按事件时间选择；缺失时失败关闭或显式标记近似，禁止静默套用当前
   规则。
8. margin、leverage bracket、mark 和 liquidation 采用版本化、保守近似；强平产生显式成交并
   进入 P05 双重记账。cross/isolated、long/short 的适用范围进入运行清单。
9. 多腿和跨所按非原子顺序执行。已成交腿不得回滚；后续失败产生裸露名义、持续时间和失败
   原因，并保持账本平衡。
10. 性能门记录事件吞吐、峰值内存和重复运行稳定哈希。优化不得改变 Decimal、事件顺序或
    账本不变量。

## 官方契约

- PyPI 稳定发布与 Windows 精度说明：<https://pypi.org/project/nautilus-trader/>
- 回测总览：<https://nautilustrader.io/docs/latest/concepts/backtesting/>
- 成交模型：<https://nautilustrader.io/docs/latest/concepts/backtesting/fill-models/>
- 事件执行顺序：<https://nautilustrader.io/docs/latest/concepts/backtesting/execution-flow/>

## 实测契约补充

- NautilusTrader `1.231.0` 的无策略 QuoteTick 探针中，3 条输入行情对应
  `BacktestResult.iterations == 3`，而 `total_events == 0`。P06 以 `iterations`
  证明数据被回放，不把 `total_events` 字段名误读为输入行情计数。

## 后果

- P06 不升级依赖，不使用预发布版，不连接任何真实场所。
- Nautilus 的性能和成熟撮合语义得到利用与验证，但 AegisQuant 保留精度、账本和审计主权。
- 所有回测输出都是研究工件，不具备下单或 `LIVE_TRADING` 解锁能力。
