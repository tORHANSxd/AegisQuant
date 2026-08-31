# 事件契约与兼容性

## 信封

所有版本化事件使用 `EventEnvelope`：

```json
{
  "schema_name": "aegisquant.market-event",
  "schema_version": "1.0.0",
  "event_id": "event-id",
  "occurred_at": "2026-08-31T08:00:00Z",
  "available_at": "2026-08-31T08:00:01Z",
  "payload": {}
}
```

`schema_name` 和 semantic version 共同选择契约。`event_id` 表达经济事实身份；同一
事实重放沿用原 ID 和幂等键。

## 序列化

- 使用 UTF-8、排序键、紧凑分隔符和末尾 LF 的 canonical JSON。
- Decimal 作为十进制字符串写入，禁止转成二进制 float。
- NaN 和 Infinity 不能进入 JSON。
- 内容哈希为 canonical bytes 的 SHA-256。
- `serialize_event()` 与 `deserialize_event()` 必须保持经济字段、Decimal scale、
  强类型 ID 和 schema version。

## Schema Registry

`schemas/events/registry.json` 固化 schema 名称、版本、Python model、相对路径、
兼容模式和文件 SHA-256。`scripts/generate_schemas.py --check` 验证生成结果没有漂移。
每份 schema 使用 JSON Schema Draft 2020-12，并由契约测试调用 metaschema 校验。

## 迁移规则

`SchemaMigrationRegistry` 注册 `schema_name + from_version -> to_version` 的显式纯函数。
迁移必须：

1. 不修改调用者提供的原 payload；
2. 逐版本推进，不允许环；
3. 找不到完整路径时失败，不猜测默认字段；
4. 迁移后由目标 Pydantic model 重新严格验证；
5. 旧原始事件和旧 schema 保持不可变。

P01 当前生产 schema 均为 `1.0.0`。兼容测试使用受控 legacy fixture 验证迁移机制，
没有捏造一个可供生产消费的旧版本。
