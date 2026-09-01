# P04 实施计划

## 目标与边界

P04 建立统一但保留场所差异的 OKX、Bybit、Deribit 公共市场数据层，并建立首批全球事件与社交情报的离线可验收适配层。P03 保持 `accepted_with_waiver`；根据项目业主决定，不执行或伪造 12/24 小时验收。

本阶段仅允许公开市场数据和合法公开内容契约。`LIVE_TRADING`、私有 API、真实账户、下单、明文凭据和 P05 账本均不在范围内。

## 实施顺序

1. 固化 35 项阶段追踪矩阵并保持安全锁。
2. 实现三家交易所的 allowlist 契约、统一 instrument、场所特定解析及 sequence 恢复。
3. 实现 canonical asset/pair/exposure、合约单位、跨场所比较、时钟偏差与 lead-lag。
4. 实现 RSS/Atom、GDELT、X、Telegram Bot、Bluesky、GitHub、YouTube 的官方契约和离线 fixtures。
5. 实现内容 revision、tombstone、engagement PIT、规则去重/实体/claim/event 与提示词注入隔离。
6. 固化来源许可、访问状态、地域/账户/产品权限和 Nautilus 兼容性证据。
7. 运行 Schema、静态分析、全量测试、候选 Python、安全与兼容测试，生成阶段八件套和清单。

## 关键决策

- 使用共享不可变模型和场所策略表，不复制三套生命周期代码。
- CI 只消费带来源说明的固定 fixtures；公开网络 smoke test是非门禁证据。
- 需要凭据的来源返回 `awaiting_credentials`，不得索取、读取或持久化凭据。
- P04 的线性/逆向公式仅验证合约单位语义，不创建 P05 会计账本。
- 优先标准库和已有依赖；若官方契约迫使版本调整，必须写 ADR。

## 验收

35 个 RTM 条目均须指向真实实现、自动测试与证据，状态全部为 `verified`；全套 CI、Secret/LIVE 锁、Schema、Nautilus 和 Python 兼容性检查必须通过，且阶段状态只推进到 P04。
