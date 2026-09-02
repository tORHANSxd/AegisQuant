# P17 采购建议

## 结论

**NO_PURCHASE：当前不采购、不批准、不接入任何付费 Provider。**

原因不是候选一定没价值，而是尚无真实试用、OOS 消融、许可确认和运维证据。桌面评审与
厂商营销字段不能代替这些证据；用户未批准任何预算，批准支出上限为 0 美元。

## 候选决策

| Provider | Group | Decision | Evidence |
|---|---|---|---|
| tardis | market_tick | DEFER | desk_review_only |
| kaiko | market_tick | DEFER | desk_review_only |
| coinglass | derivatives_aggregate | DEFER | desk_review_only |
| cryptoquant | onchain_metrics | DEFER | desk_review_only |
| glassnode | onchain_metrics | DEFER | desk_review_only |
| databento | cross_asset_cme | NOT_APPLICABLE | not_tested |
| benzinga | news_personal | DEFER | desk_review_only |
| event_registry | news_personal | DEFER | desk_review_only |
| cryptopanic | news_personal | DEFER | desk_review_only |
| ravenpack | news_institutional | DEFER | desk_review_only |
| bigdata_com | news_institutional | DEFER | desk_review_only |
| lseg_mrn | news_institutional | DEFER | desk_review_only |
| x_api | x_social | DEFER | desk_review_only |

## 重新启动试用的硬条件

1. 用户先批准对应 `TRIAL_REQUESTS.json` 中的范围、最长时长和成本硬上限。
2. 凭据仅由用户写入本地秘密库；聊天、Markdown、配置和报告只记录引用状态。
3. 真实 Provider 数据必须按 available_time 保存，并与官方交易所或官方发布源交叉核验。
4. 只有 OOS 净增量、许可、成本和运维门全部通过，才可在同类中批准最多一家。
5. 任一 Provider 停服必须退回免费基线；第三方聚合永不替代官方交易事实。

正式验收仍延期；未执行 12h/24h，也未生成 P17 `ACCEPTANCE.md`。
