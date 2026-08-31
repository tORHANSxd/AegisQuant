# ADR-0006：Binance 公开市场数据契约与安全边界

- 状态：Accepted for P03 implementation
- 日期：2026-08-31

## 决策

P03 使用 AegisQuant 原生公开数据适配器接入 Binance Spot 与 USDⓈ-M Futures，并保留
NautilusTrader 作为后续交易/回放引擎的兼容对象。适配器只允许官方公开市场数据端点，
不接受凭据、Cookie、签名参数、用户数据流、账户、订单或私有路由。

Spot REST 优先使用 `https://data-api.binance.vision`，Spot WS 使用
`wss://data-stream.binance.vision`。USDⓈ-M 高频订单簿类流使用
`wss://fstream.binance.com/public`，成交、Kline、Mark 等市场流使用
`wss://fstream.binance.com/market`；明确禁止 `/private` 和已经退役的无路由入口。

`httpx==0.28.1` 和 `websockets==17.1` 作为精确锁定的网络依赖，实际契约必须在 Python
3.13.15 和 3.14.7 上验证。HTTP 客户端关闭环境凭据、Cookie、自动重定向和隐式代理继承。

公开原始响应使用新增的 `PUBLIC_APPEND_ONLY` 策略模式：原始字节以不可变目录、内容哈希
和原子发布保存。受限内容仍必须使用 `ENCRYPTED_LOCAL`，二者不得混用。此模式避免用无法
恢复的临时密钥冒充生产归档，也不会降低现有受限内容保护。

## 依据

- Binance Spot REST/WS 官方文档与 Changelog，复核日期 2026-08-31。
- Binance USDⓈ-M Futures 官方 REST、WS 路由变更、连接和盘口重建文档。
- Binance 公共历史数据仓库的 `.CHECKSUM` SHA-256 契约。
- 本地 `nautilus-trader==1.231.0` 的 URL helper 已区分 USDⓈ-M `/public` 与 `/market`；
  但其内存数据加载器不替代 P02 的不可变数据湖、来源政策、PIT 和原始响应归档。

## 后果

- CI 只使用提交的 fixture；实时网络检查不进入 CI。
- 新 Binance 状态（例如 `CANCEL_ONLY`）以原始字符串保留，未知值不会令 instrument 解析崩溃。
- 429 必须遵循 `Retry-After`；持续超限或 418 进入 halt，不进行激进重试。
- P03 的 24 小时验收必须跨越主动换线或恢复流程，不能通过加速时钟替代。

## 实际契约观察

2026-08-31 的公共 smoke 观察到 USDⓈ-M `/public` 深度帧额外包含 `ps`、`st`，
`/market` aggTrade 帧额外包含 `nq`、`st`，Mark Price 帧额外包含 `ap`、`st`。
适配器只依赖官方序列与价格必需字段，未知新增字段不得令解析失败；原始响应归档与录制
fixture 保留完整字段，以便 Changelog watcher 和后续 schema 版本显式吸收变化。
