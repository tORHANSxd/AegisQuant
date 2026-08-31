# PIT Leakage Tests

- 状态：`passed`
- 通过：6
- 命令：`-m pytest tests/property/test_data_properties.py tests/p02/test_pit_query.py -q`
- 耗时：2.269717 秒

覆盖 `event_time <= decision_time`、`available_time <= decision_time`、未来 revision、未来互动
快照、非法 SQL 标识符和 Hypothesis 随机可用时间。查询实现通过严格标识符 allow-list 和
DuckDB LATERAL latest-visible join 执行；任何未来可用事实只能返回空值，不能进入特征。
