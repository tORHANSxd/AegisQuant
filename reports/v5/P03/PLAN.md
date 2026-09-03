# V5-P03 — Evidence Retrieval + Independence Graph

- Evidence Tier: `DEVELOPMENT`
- Alpha Promotion Eligible: `false`
- Live Trading Locked: `true`

## 规格边界

本阶段严格对应 v5 SSOT 第 441–557 行及 V5-P03 第 2078–2101 行，只实现双向证据检索
契约、PIT 命中选择、provenance graph 依赖识别和 dependency scoring。P04 Truth Council、
概率校准、P05 事件 surprise、P06 causal layer 及所有交易 Promotion 均不提前实现。

## 实施顺序

1. 建立六类非空 `EvidenceSearchPlan` 查询，强制 support 与 contradiction 同时存在。
2. 将命中绑定到 query hash、claim、source identity、document revision、PIT 时间、rights、
   deletion、official identity 和 lineage。
3. 只选择 decision time 前已检索的最新可用 revision；未来、已删除以及 rights 为
   `UNKNOWN`/`PROHIBITED` 的命中不进入证据集。
4. 用显式 provenance edge、内容 hash、共同 origin 指纹和 independence group 计算依赖
   连通分量。
5. 构造十篇来自同一原始 rumor 的机器改写，验收独立证据数为 1、依赖度为 0.9。
6. 生成 schema、确定性开发证据、负向测试、完整 CI 和内容寻址工件清单。

## Acceptance

- 六类查询均非空，support 与 contradiction 不得重合或缺失。
- Agent 投票比例不得作为最终 probability aggregation。
- official denial 必须绑定已验证的官方身份和否定 polarity。
- PIT 选择不得看到未来 revision，并过滤已删除与 rights unknown/prohibited 命中。
- 十篇来自同一 rumor 的文章必须得到 `independent_evidence_count=1`，不是 10。
- 完整 V5-P03 CI、历史 phase manifest SHA 和最终当前工件清单全部通过。
