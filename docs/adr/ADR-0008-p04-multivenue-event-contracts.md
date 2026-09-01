# ADR-0008：P04 多场所公共数据与事件来源契约

- 状态：Accepted for P04 implementation
- 日期：2026-09-01

## 背景

任务书要求同时接入 OKX、Bybit、Deribit 及首批事件/社交来源，但不能用统一 symbol 掩盖合约、结算、序列、许可或访问状态差异。相关平台契约和价格会变化，因此实现以 2026-09-01 复核的官方稳定文档、本地锁定依赖和自动契约测试为准。

## 决定

采用“共享不可变市场模型 + 场所契约表 + 场所特定 normalizer/sequence”结构。Canonical Exposure 由 base/quote/settlement、instrument type、linear/inverse、expiry、strike 和 option type 共同决定；场所 instrument ID 仍包含 provider、venue symbol 和 exposure ID。

- OKX 使用无需登录的 `books` 与公共 REST；`books-l2-tbt`、`books50-l2-tbt` 需要登录/等级条件，不纳入 P04。
- Bybit 以 `category` 区分 spot/linear/inverse/option，instrument 分页上限与 cursor 进入契约；订单簿处理 snapshot/delta、`u=1` 重启和 `seq/u` 顺序语义。
- Deribit 保留 `contract_size`、`instrument_type`、settlement、expiry、strike、option type；订单簿以 `change_id/prev_change_id` 恢复，期货与期权数量单位不混用。
- P04 只提供合约单位与正/逆向公式测试，不创建 P05 的头寸、账本或权威 PnL 状态。
- 本地 `nautilus-trader==1.231.0` 的 OKX、Bybit、Deribit 模块通过运行时发现验证；无模块或语义不满足时，使用已测试的 AegisQuant 原生公开路径。

事件来源采用官方契约与统一 `CollectedContent -> SourceIdentity/RawContentEnvelope -> append-only projection` 流程。RSS/Atom、GDELT、Bluesky Jetstream 和 GitHub 公共契约可处于 `ready`，但采集默认关闭；X、Telegram Bot 和 YouTube 在无凭据时必须为 `awaiting_credentials`，只运行 fixtures。MTProto 禁用并等待独立安全评审。Reddit、Discord、微博和 TikTok 默认关闭。

外部内容永远作为数据处理。规则流水线可以标记 prompt injection，但没有工具调用、配置修改、账户或交易权限。互动量按 observation/available time 追加快照，不回填历史特征；revision 和 deletion 传播到 cache/read model，并保留 tombstone。

## 官方契约依据

- OKX API 与 Changelog：<https://www.okx.com/docs-v5/en/>
- Bybit instrument 与 orderbook：<https://bybit-exchange.github.io/docs/v5/market/instrument>、<https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook>
- Deribit instrument 与 orderbook：<https://docs.deribit.com/api-reference/market-data/public-get_instrument>、<https://docs.deribit.com/subscriptions/orderbook/bookinstrument_nameinterval>
- NautilusTrader integrations/options：<https://nautilustrader.io/docs/latest/integrations/>、<https://nautilustrader.io/docs/latest/concepts/options/>
- X filtered stream 与访问额度：<https://docs.x.com/x-api/posts/filtered-stream/introduction>、<https://docs.x.com/x-api/fundamentals/post-cap>
- Telegram Bot API：<https://core.telegram.org/bots/api/>
- Bluesky Jetstream：<https://github.com/bluesky-social/jetstream>
- GitHub Releases：<https://docs.github.com/en/rest/releases/releases>
- YouTube Data API：<https://developers.google.com/youtube/v3/getting-started>

## 后果与回退

- 未新增依赖；XML 使用有大小上限、拒绝 DTD/ENTITY 的标准库解析。
- CI 只使用明确标注为 contract-derived/synthetic 的 fixtures，不伪称已连通凭据源。
- Provider 许可状态与运行访问状态分离，避免把 `approved` 错当成“当前可访问”。
- API 字段、限频、付费或协议发生变化时，先更新契约测试和本 ADR 的 superseding ADR，再修改实现；不得静默兼容私有端点。
- P03 的 24 小时豁免仍由 ADR-0007 管理，P04 不执行、拼接或改名生成该证据。
