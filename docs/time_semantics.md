# 时间语义

## 五类时间

| 字段 | 含义 |
|---|---|
| `event_time` | 事实在来源系统发生的时间 |
| `available_time` | 事实首次可被本系统合法获得的时间 |
| `ingest_time` | 本系统实际接收或导入时间 |
| `processed_time` | 当前处理步骤完成时间 |
| `revision_time` | 来源修订历史事实的时间，可为空 |

内部只接受 timezone-aware datetime，并在验证时规范化为 UTC。naive datetime 会以
`AQ-TIME-NAIVE` 拒绝；展示层才允许转换为用户时区。

## 顺序与 PIT

- 市场事件满足 `available_time <= ingest_time <= processed_time`。
- 回测或决策读取满足 `available_time <= decision_time`，否则触发
  `AQ-TIME-LOOKAHEAD`。
- revision 追加新 vintage，不覆盖旧版本。
- K 线的 event/end time 与 available time 分离；完整收盘值只能在其可用后读取。
- venue server time、本地 UTC wall clock 和本地 monotonic clock 是不同观测量；
  monotonic clock 只用于测量持续时间，不能写作市场时间戳。

## Clock

领域边界依赖 `Clock` 协议。运行时使用 `SystemClock`，测试和回放使用
`FixedClock`。模块导入期间不采样时间，不调用无时区 `datetime.now()` 或
`datetime.utcnow()`。

## PostgreSQL

所有持久化时间列使用 `TIMESTAMP WITH TIME ZONE`。数据库连接和应用仍以 UTC
语义处理；PostgreSQL 会按 session timezone 展示值，因此比较和序列化不能依赖
展示字符串。
