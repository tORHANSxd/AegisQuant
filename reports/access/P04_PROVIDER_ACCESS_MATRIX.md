# P04 Provider 访问与权限矩阵

| Provider | 公共数据 | 凭据 | 当前状态 | 地域/账户/产品限制 | P04 行为 |
|---|---:|---:|---|---|---|
| OKX | 是 | 否 | `ready` | 仅公开 market/instrument；遵守当地访问规则 | REST/WS 契约和 fixture 验收 |
| Bybit | 是 | 否 | `ready` | 仅公开 V5 market；遵守当地访问规则 | REST/WS 契约和 fixture 验收 |
| Deribit | 是 | 否 | `ready` | 仅公开 futures/options；遵守当地访问规则 | REST/WS 契约和 fixture 验收 |
| RSS/Atom | 是 | 否 | `ready` | 仅官方 allowlist | 默认不启动采集 |
| GDELT | 是 | 否 | `ready` | 仅用于发现，不作为权威证据 | 默认不启动采集 |
| X | 否 | 是 | `awaiting_credentials` | 付费额度、条款和用户批准均待确认 | 只验收契约和 fixture |
| Telegram Bot | 否 | 是 | `awaiting_credentials` | 频道 allowlist 为空；MTProto 禁用 | 只验收契约和 fixture |
| Bluesky Jetstream | 是 | 否 | `ready` | 版本探测、断点和 Firehose 回退必需 | 默认不启动采集 |
| GitHub | 是 | 否 | `ready` | 仅公开 Release/Advisory/Webhook fixture | 默认不启动采集 |
| YouTube | 否 | 是 | `awaiting_credentials` | API 项目、配额、直播聊天授权待确认 | 只验收契约和 fixture |

`ready` 仅表示无需用户凭据即可使用公开契约，不表示后台采集已启动。所有 `collection_enabled` 仍为 `false`。本阶段未连接账户、未读取私有数据、未写入任何 Secret。
