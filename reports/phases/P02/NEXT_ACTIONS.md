# P02 后续动作

P02 已收口。以下是待办和未来进入条件，不代表 P03 已获批准或已经开始。

1. 等待用户明确批准 Phase P03；批准前不得接入 Binance、交易所 WebSocket/REST、
   Provider Worker、真实账户或私有接口。
2. 如需清点真实本地资产，用户必须提供精确目录并明确授权只读扫描；扫描器仍不得执行、
   导入、移动、改写或删除任何源文件，只能生成 inventory 与 import proposal。
3. 在真实 100/200 GiB 规模验证前，准备至少 500 GiB 可用工作空间，分别测冷盘/热盘、
   分区裁剪、多列查询和并发负载；不得复用当前线性外推冒充 SLA。
4. 配置独立备份目标后，验证 schema registry → manifest/catalog → 内容哈希 → 派生层重建
   的完整恢复顺序，以及 tombstone 的备份删除传播。
5. 监控与 PyArrow 25 对齐的 `pyarrow-stubs`；升级 DuckDB/Polars/PyArrow 前重跑双
   Python、PIT、安全配置与 Parquet round-trip 契约，并以新 ADR 记录语义变化。
6. 继续保持所有明文密码、Cookie、验证码和 API Secret 禁止写入；真实账户和秘密存储
   保持不可访问；`LIVE_TRADING` 保持锁定。
7. P03 若获批准，必须先重新读取任务书对应章节、现有 P02 八件套和风险台账，建立新的
   需求追踪切片与实施计划后再执行。

当前允许的动作仅限 P02 证据维护、缺陷修复和经用户明确授权的只读资产清点。
