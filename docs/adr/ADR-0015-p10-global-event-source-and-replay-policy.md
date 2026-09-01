# ADR-0015：P10 全球事件来源、证据独立性与回放政策

- 状态：Accepted by project owner through autonomous P10 execution authorization
- 日期：2026-09-02

## 背景

P10 同时面对宏观 vintage、链上与 SQL 查询结果、官方公告、新闻发现、社交媒体修订/删除、互动
增长、跨语种翻译和 LLM 推理。它们的共同风险不是“数据不够多”，而是可用时间、原始来源、权利、
重复转发和后续修订被揉成一锅粥，回测就能轻易看见未来。部分生产源还要求开发者账户或 API key；
没有凭据时若用夹具冒充生产接入，属于拿纸糊雷达，风一吹就露馅。

官方稳定契约与旧实现存在一项明确偏差：Bluesky Jetstream 当前 v2 规范使用
`/xrpc/network.bsky.jetstream.subscribeEvents`、带 `payload` 的事件包装、单调 `seq` 游标以及
snapshot/backfill/cutover 计划；P04 既有实现采用 legacy v1 `/subscribe`、`time_us`/`cursor` 结构。
P10 因此需要升级主契约，同时保留明确标注的 v1 兼容回退。

## 决定

1. 每个内容与数值记录至少保留 `event_time`、`source_time`、`ingested_at`、`available_at` 和
   `knowledge_time/as_of`。查询、模型、事件簇与回放只能读取 `available_at <= as_of` 的版本；缺失
   可用时间时失败关闭，不用发布时间猜到达时间。
2. FRED/ALFRED 使用官方 `realtime_start`/`realtime_end`、`vintage_dates` 及 observation 输出类型
   建模。每个观察值保留 vintage；首发、修订和当前值不能相互覆盖。
3. Coin Metrics Community 使用 `https://community-api.coinmetrics.io/v4`，遵守公开配额、分页和
   reviewed/revised 状态；DeFiLlama 免费源只使用 `https://api.llama.fi`，不得与 Pro key 路径混用。
4. Dune 只允许登记用户批准的只读查询。查询注册表保存 query ID、SQL 文本的内容哈希与版本、参数
   架构、execution ID、执行状态、结果哈希和可用时间。API key 只通过本地秘密引用注入，禁止进入
   URL、日志、工件或对话；未配置时保持 `AWAITING_CREDENTIALS`。
5. GDELT 仅作为发现层，事件证据必须继续追到原始发布者 URL/身份与抓取版本。聚合页、搜索摘要或
   转发不是原始来源，不因数量多自动增加独立证据。
6. X、Telegram、YouTube 与需要认证的 GitHub 能力在本地秘密引用缺失时安全降级；Telegram 只使用
   Bot API 和用户批准的公开频道，不索取用户会话、Cookie 或验证码。公共 GitHub 只读契约固定 REST
   API version；YouTube 记录配额成本和资源版本，不抓取无授权字幕。
7. Bluesky 以 Jetstream v2 XRPC 路径、`seq`、`kind`、`collection`、DID 过滤、`CursorTooOld` 和
   snapshot/backfill/cutover 为主契约。legacy v1 只作为显式兼容回退，保存 `time_us`/`cursor`，且
   不把 36 小时回看窗口当完整历史。
8. 所有来源默认只读。来源权利矩阵分别决定本地原文存储、云推理、嵌入、训练/微调、展示、导出、
   删除同步和保留期；`unknown` 默认关闭云、训练、展示与导出。删除事件保留合规所需的哈希、时间和
   tombstone，不继续公开已删除正文。
9. 原文不可变保存，规范化与翻译为派生版本。翻译记录必须包含语言、模型/供应方/版本、提示或规则
   版本、置信度、输入/输出哈希和人工复核状态；P10 不提供假装支持所有语言的占位翻译器。
10. 重复与证据独立性分层计算：同内容、近重复、引用、转发及共同上游归入 source family。无论有
    多少条转发，同一上游家族最多贡献一份独立支持；独立性、官方性、域准确度、更正记录、操纵风险
    与热度分开保存。
11. 高影响 EventCluster 必须连接 Claim、支持/反驳证据、来源版本与政策、实体、本体版本、模型版本、
    委员会冲突、Skeptic 结论和结构化弃权。Fast/Deep 路径可以算力不同，但不得放宽证据和安全门禁。
12. 事件模型只产生多资产、多时域 `EventImpactForecast` 或风险 Proposal；不得构造 OrderCommand。
    Risk-only 输出只允许经 P05/P08 风控链影响风险预算或禁用状态，单条社交帖子不能直接下单。
13. Market-only、Event-only、Fused、Risk-only 使用相同 OOS 窗口、数据截止时间、样本、计算预算和
    成本规则。报告保留正负结果，不从四个视角中事后挑冠军。
14. 事件回放保留首版、全部修订、删除 tombstone 和每个互动快照。强制执行未来互动泄露、5 秒/
    30 秒/2 分钟/10 分钟延迟压力、趋势前置和安慰剂检查；任何失败都进入证据而非被静默过滤。
15. 来源或 LLM 不可用时只允许显式 `DEGRADED`/`AWAITING_CREDENTIALS`/`DISABLED_BY_POLICY` 状态，
    使用缓存或本地确定性规则时仍需满足 as-of 与权利政策。Reddit、Discord 和未知权利来源默认禁用。
16. 正式验收继续按 ADR-0010 延期；`LIVE_TRADING=false`、`live_trading_locked=true`。P10 不连接
    真实交易账户、生产下单端点或未授权私域来源。

## 后果

- 源接入数量可能比“全网抓取”少，凭据缺失时生产状态也不会好看，但证据链和降级状态是真实的。
- 保存版本、游标、SQL 哈希和互动快照增加存储量，却能防止修订与未来热度偷渡进回测。
- 一百条转发只算一个家族会压低表面置信度；这正是需要的，复读机不是一百位独立证人。
- Jetstream v1 夹具需要迁移或兼容解析，v2 游标不能再错误地使用 `time_us` 代替 `seq`。

## 外部契约依据

- FRED series observations：<https://fred.stlouisfed.org/docs/api/fred/series_observations.html>
- FRED realtime period：<https://fred.stlouisfed.org/docs/api/fred/realtime_period.html>
- FRED vintage dates：<https://fred.stlouisfed.org/docs/api/fred/series_vintagedates.html>
- Coin Metrics API v4：<https://docs.coinmetrics.io/api/v4/>
- Coin Metrics Community API：<https://docs.coinmetrics.io/api>
- Dune Execute SQL：<https://docs.dune.com/api-reference/executions/endpoint/execute-sql>
- Dune execution object：<https://docs.dune.com/api-reference/executions/execution-object>
- Dune query object：<https://docs.dune.com/api-reference/queries/endpoint/query-object>
- DeFiLlama API：<https://api-docs.defillama.com/>
- Bluesky Jetstream v2：<https://github.com/bluesky-social/jetstream/blob/main/docs/README.md>
- X filtered stream：<https://docs.x.com/x-api/posts/filtered-stream/introduction>
- Telegram Bot API：<https://core.telegram.org/bots/api/>
- YouTube Data API videos.list：<https://developers.google.com/youtube/v3/docs/videos/list>
- GitHub Releases REST API：<https://docs.github.com/en/rest/releases?apiVersion=2026-03-10>

## 回退条件

若官方稳定接口废弃上述版本、字段、配额或授权方式，应以契约测试验证的新版本另立 ADR；不得通过
静默容错把未知字段、旧游标或缺失时间解释为可用数据。若来源权利收紧，立即关闭相应用途并保留
政策变更证据，不以历史许可继续新增处理。
