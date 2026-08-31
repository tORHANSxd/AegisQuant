# P02 实施计划

## 目标

建立不可变 Parquet 数据湖、Provider Registry、数据清单、point-in-time 语义、质量
隔离、只读本地资产扫描器和最小 Data Catalog/CLI。P02 只建立数据底座，不接入交易所
私有接口，不执行用户文件，不导入未知策略，不开始 P03。

## 规格基线与批准

- 规格版本：`3.1.0`
- 根规格 SHA-256：`1265a4feeb126bf9004685b80c0aa01d053fd983079b80d5c9063abefc382d1f`
- P01 状态：`accepted`
- P02 执行批准：用户于 2026-08-31 明确要求“继续”
- 安全默认值：`LIVE_TRADING=false`
- 用户本地路径：未提供；只允许合成目录夹具，不得宣称扫描过真实用户资产

## 范围

1. 完整 `ProviderRegistryEntry`、访问/许可状态、来源政策绑定和采集前 fail-closed gate。
2. RAW/BRONZE/SILVER/GOLD/QUARANTINE 分层路径、追加写、原子发布与不可变清单。
3. 内容哈希、checkpoint、schema registry、转换 lineage 和确定性 dataset ID。
4. DuckDB 查询层、Polars lazy 变换和 PyArrow Parquet 批式读写。
5. 数据质量规则、机器可读报告、quarantine 以及 Gold 禁入门。
6. `event_time/available_time/ingest_time/revision_time` 与内容观察/修改/删除/互动快照语义。
7. revision、tombstone、删除传播和 AES-GCM 受限内容加密；密钥只由调用方在内存提供。
8. point-in-time join、未来数据/未来互动/最终修订泄漏属性测试。
9. 只读流式目录扫描、哈希/重复/schema/时间范围识别和 import proposal。
10. Data Catalog、DuckDB 查询和不执行未知文件的最小 CLI。
11. 合成大目录/短文本基准，以及 Apache 官方公开 Parquet 兼容样本。
12. 存储容量、备份、保留、删除和重建建议。

## 依赖与版本决策

- 候选稳定版：DuckDB 1.5.5、Polars 1.44.1、PyArrow 25.0.1、cryptography
  50.0.1、psutil 7.2.2。
- 所有直依赖必须精确锁定，并在 Python 3.13.15、3.14.7 和 Windows x64 实际安装、
  import、Parquet round-trip、PIT 查询和加密 round-trip 后才可接受。
- 若最新稳定版缺少兼容 wheel 或契约失败，选择最近兼容稳定版并记录 ADR；禁止本地
  临时编译后冒充可重复安装。

## 实施顺序

1. 更新阶段状态与需求追踪，将 P00/P01 保持为历史 verified、P02 标为 planned。
2. 锁定列式/加密/监控依赖并建立 ADR、兼容性契约。
3. 实现数据模型、Provider Registry、政策 gate、清单和 lineage。
4. 实现不可变湖写入、checkpoint、原子发布、revision/tombstone 与加密归档。
5. 实现质量/quarantine、PIT join 和 DuckDB/Polars/PyArrow 查询转换。
6. 实现只读扫描、import proposal、Data Catalog 与 CLI。
7. 生成合成资产清单、公开样本证据、容量/生命周期建议和性能报告。
8. 运行静态、单元、属性、契约、Chaos、性能、安全、供应链和前端回归门禁。
9. 生成 P02 八件套、工件清单、验收状态和 Git 归档。

## 验证门禁

- 同一输入字节与相同转换契约必须产生相同 dataset ID、文件哈希和清单哈希。
- 临时写入、进程中断或异常不得留下已登记但文件不完整的数据集。
- RAW/BRONZE 只能追加；修订和删除通过新版本/tombstone 表达，不覆盖原始事实。
- PIT join 只能选择 `available_time <= decision_time` 的版本，并确定性处理 revision。
- quarantine 数据不得进入 Gold，质量失败不得通过改名或手工复制绕过。
- 扫描器不得写、移动、删除或执行源文件；未知文件只能生成 import proposal。
- Provider 未登记、许可未知或政策未批准时，采集和归档必须 fail closed。
- 基准必须报告真实样本规模、RSS 峰值、吞吐和 100/200GB 外推方法；禁止生成会耗尽
  本机磁盘的假“大文件”。
- 完整 P00/P01 安全回归通过，`LIVE_TRADING` 始终锁定。

## 外部输入与公共样本边界

没有用户提供的本地路径，因此 `LOCAL_ASSET_INVENTORY` 只描述合成夹具并明确
`real_user_assets_scanned=false`。唯一允许的外部数据是无认证、Apache-2.0、固定 commit
和 SHA-256 的 Apache Parquet 官方兼容测试小样本；它只验证格式互操作，不代表任何
交易或用户数据源已获批准。

## 非目标

- 不接入 Binance、OKX、Bybit、Deribit 或社交 Provider；这些属于 P03/P04。
- 不扫描未获授权路径，不读取浏览器、秘密存储或真实账户。
- 不执行、导入、移动或改写发现的脚本、Notebook、策略或数据文件。
- 不实现对象存储、Kafka、云密钥管理、业务 API 或 Web 数据页面。
- 不创建 Live Adapter，不解除或弱化任何交易锁，不开始 P03。

## 失败策略

任何原子性、PIT、不可变性、来源政策、扫描只读性、加密或 Live 锁门失败，P02 必须
保持 `in_progress` 或标记 `blocked/failed`。不得用跳过、Mock 列式栈、伪造用户清单、
占位基准或降低数据安全要求宣称验收通过。
