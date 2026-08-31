# P01 领域模型

## 边界

`src/aegisquant/domain/` 是纯领域包。它只依赖 Python 标准库和 Pydantic 的契约
验证能力，不依赖 SQLAlchemy、Alembic、Psycopg、FastAPI、NautilusTrader 或任何
交易所 SDK。数据库映射位于 `src/aegisquant/persistence/`，两者之间没有反向导入。

P01 固化对象、语义和可执行不变量，不实现完整会计引擎、组合优化器、风险引擎、
订单状态机或交易所适配器。

## 标识符和值对象

- 每类内部身份使用不同的 `TypedId` 子类；外部 ID 继承独立的 `ExternalId`。
- ID 可以由 namespace UUID 或精确内容 SHA-256 确定性生成，不依赖数据库自增列。
- `Money`、`Quantity` 和 `Price` 使用 `Decimal`，携带资产或交易对单位。
- 值对象拒绝 float、NaN、Infinity 和负零；不同单位不能相加减。
- 量化必须提供正的市场规则 increment 和显式 `RoundingMode`，不得调用 `round()`。

## 参考实体

`Asset`、`Venue`、`Environment`、`Account` 和 `Instrument` 为不可变严格模型。
`Instrument` 保存有效时间区间、来源快照和当时的 tick、step、最小数量、最小名义
金额等规则。历史计算按 `valid_from <= decision_time < valid_to` 选择版本，禁止拿
当前规则覆盖历史。

## 情报到决策的单向链

```text
RawContentEnvelope
  -> ClaimRecord
  -> EventCluster / NarrativeState
  -> EventImpactForecast
  -> ForecastBundle
  -> AlphaSignal
  -> PortfolioProposal
  -> RiskDecision
  -> OrderIntent
```

`AlphaSignal` 没有下单字段。事件预测只允许成为 `ForecastBundle` 的输入；只有不可
变的 `RiskDecision` 可以授权 `OrderIntent`。策略不能修改风险决定，也不能绕过它
直接构造经济命令。

## 来源处理策略

每个外部内容来源必须绑定 `SourceProcessingPolicy`。`evaluate()` 和 `require()` 在
采集、归档、云推理、训练、展示、导出和删除边界执行判断。未明确 `APPROVED` 的
策略在处理边界默认拒绝；删除请求本身永不被阻止，但会返回同步删除和追加
tombstone 的必需动作。

## 订单事实

- `OrderIntent`：风险批准后的经济意图。
- `OrderCommand`：面向具体 venue 的 PLACE、CANCEL 或 AMEND 命令契约。
- `VenueOrder`：交易所事实；本地 `SUBMITTED` 不等于 venue `ACCEPTED`。
- `Fill`：带 venue FillId、价格、数量、手续费和三类时间的成交事实。
- `OrderRecoveryCase`：未知状态的证据、复查和对账记录。

P01 没有任何发送命令的 Adapter、网络调用或 Live 解锁路径。

## 会计不变量

`JournalEntry` 至少包含两笔 `LedgerPosting`，并按每种资产分别验证借贷相等。
posting 金额为正，借贷方向独立表达。对账调整必须显式引用被补正的历史 entry，
不得覆盖旧记录。`PositionLot` 固化开仓量、剩余量、价格、费用和关闭时间的一致性。
