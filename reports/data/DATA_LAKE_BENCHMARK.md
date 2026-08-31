# Data Lake Benchmark

## 实测范围

- 行数：1000000
- 分批：100000 rows/batch
- Row groups：10
- 压缩 Parquet：10014329 bytes
- 写入：0.680446 秒，1469623.47 rows/s
- DuckDB 聚合：0.028985 秒，34500008.78 rows/s
- 压缩字节吞吐：329.489 MiB/s
- 写入 RSS 采样峰值增量：64622592 bytes
- 查询 RSS 采样峰值增量：66289664 bytes
- 全文件装入 RAM：`false`

## 100/200 GiB 外推

- 100 GiB 单列顺序扫描估算：310.784 秒
- 200 GiB 单列顺序扫描估算：621.568 秒

外推按实测压缩字节吞吐线性计算，只是容量规划下界，不等于真实多列、并发或冷盘性能。
生产查询必须依赖日期/provider/dataset 分区裁剪、列裁剪和增量处理，禁止把 100/200 GiB
全部物化到 Python 内存。实测文件只存在于临时目录，完成后销毁。

## 生命周期与恢复建议

- 200 GiB 逻辑数据集预留至少 500 GiB 工作空间，覆盖不可变版本、compaction staging 与 20% 余量。
- Catalog、manifest、schema registry 和 tombstone 每次提交后做独立校验备份；数据文件按内容哈希去重备份。
- RAW/BRONZE 只追加；修订写新版本。删除先追加 tombstone，再按来源政策传播到派生数据和备份索引。
- 恢复顺序：schema registry → manifest/catalog → 内容哈希核验 → 派生层重建；不从 Gold 反推 Raw。
