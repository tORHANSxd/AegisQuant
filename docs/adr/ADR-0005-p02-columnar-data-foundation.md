# ADR-0005：P02 列式数据底座与本地安全查询契约

- 状态：Accepted
- 日期：2026-08-31
- 决策阶段：P02
- Supersedes：无

## 背景

任务书要求 P02 建立不可变 Parquet 数据湖、DuckDB/Polars/PyArrow 列式栈、来源政策、
point-in-time 防泄漏、加密修订、只读资产扫描和 100/200 GiB 容量估算。任务书中的外部
版本只能作为候选；最终选择必须以官方稳定版本、Windows wheel 和实际契约为准。

## 决定

1. 生产 Python 仍固定为 3.13.15，3.14.7 只作为兼容候选。列式与安全直依赖精确固定为：
   DuckDB 1.5.5、Polars 1.44.1、PyArrow 25.0.1、cryptography 50.0.1、psutil 7.2.2。
2. `pyarrow-stubs` 当前可用稳定包为 20.0.0.20260819，落后于 PyArrow 25 API。保留严格
   Pyright，不降低告警；只在 Arrow/Parquet 调用边界用窄 `Protocol`/`cast` 适配，并用
   Python 3.13/3.14 实际 round-trip 契约兜底。
3. DuckDB 连接只使用内存数据库，关闭扩展自动安装/自动加载、社区扩展、未签名扩展、
   持久 secret 和外部访问；本地 Parquet 只允许显式根目录，配置完成后执行
   `lock_configuration=true`。
4. DuckDB 1.5.5 在未加载 `httpfs` 时不存在 `enable_global_s3_configuration` 设置；实际
   合约返回它属于 `httpfs` 扩展。为避免为了关闭一个设置反而加载网络扩展，不设置该项，
   以 `enable_external_access=false`、禁用扩展自动加载和路径 allow-list 形成闭环。
5. `fetch_arrow_table()` 在 1.5.5 发出弃用警告，改用 `to_arrow_table()`，并由契约测试覆盖。
6. 受限原始内容使用调用方内存持有 256-bit key 的 AES-256-GCM revision archive；普通
   Parquet writer 不接受“已经加密”的布尔自证。`ENCRYPTED_LOCAL` 的 RAW/BRONZE 请求
   必须转入加密 revision archive，避免产生可读明文 Parquet。
7. Apache Parquet compatibility sample 只从固定 commit
   `09f3cdbde45302f0f0c689c950e465e98a9df960` 读取到内存，校验 SHA-256
   `12a618d20a59ee0967fef45e7ec1ff6d451e724838edc1bbeac780ca15e8fcc4` 和 Git blob SHA-1，
   仓库不保留原始字节。
8. 用户未授权任何本地路径，因此正式 inventory 只由运行时创建并销毁的 4,096 文件合成
   夹具生成；`real_user_assets_scanned=false` 是验收事实，不把合成结果冒充真实资产发现。

## 官方来源与实际证据

- DuckDB 配置与安全：<https://duckdb.org/docs/stable/configuration/overview.html>、
  <https://duckdb.org/docs/stable/operations_manual/securing_duckdb/overview.html>
- PyArrow 安装：<https://arrow.apache.org/docs/python/install.html>
- PyPI 固定版本：<https://pypi.org/project/duckdb/1.5.5/>、
  <https://pypi.org/project/polars/1.44.1/>、
  <https://pypi.org/project/pyarrow/25.0.1/>、
  <https://pypi.org/project/cryptography/50.0.1/>、
  <https://pypi.org/project/psutil/7.2.2/>
- AES-GCM API：<https://cryptography.io/en/latest/hazmat/primitives/aead/#cryptography.hazmat.primitives.ciphers.aead.AESGCM>
- 公开 Parquet 样本：<https://github.com/apache/parquet-testing/tree/09f3cdbde45302f0f0c689c950e465e98a9df960/data>
- 本地证据：`reports/data/P02_DATA_EVIDENCE.json`、
  `reports/data/DATA_LAKE_BENCHMARK.md`、`reports/data/PIT_LEAKAGE_TESTS.md`、
  `reports/phases/P02/PYTHON_314_CONTRACT.json`。

## 后果

- 好处：所有数据读取都能由来源政策、内容哈希、manifest、schema、lineage 和 PIT 时间语义
  追踪；网络扩展和任意路径读取默认不可用；受限原文不存在“只靠布尔参数声称已加密”的洞。
- 代价：PyArrow 运行时与第三方 stubs 主版本不一致，需要保留窄适配边界；Raw 文本不能直接
  进入普通 Parquet writer；真实 100/200 GiB 冷盘性能仍需未来有足够容量的主机复测。
- 未授权用户目录保持不可见，不能以 P02 验收结果推断任何真实历史数据或策略资产存在。

## 回退与复审条件

- `pyarrow-stubs` 发布与 PyArrow 25 对齐版本并通过双 Python 契约后，删除对应类型适配。
- DuckDB 配置项或安全语义变化时，先更新实际契约，再修改连接基线；不得为设置一个扩展专属
  开关而自动加载网络扩展。
- 若未来引入经验证的 Parquet modular encryption 或加密文件系统，可用新 ADR 扩展 RAW
  Parquet；在此之前继续使用 AES-GCM revision archive。
