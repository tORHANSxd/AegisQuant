# ADR-0026：V5-P03 证据检索与独立性计算边界

- 状态：Accepted
- 日期：2026-09-03
- 决策范围：Evidence Retrieval、PIT 命中选择与 Evidence Independence

## 背景

文章数量不是独立证据数量。转载、机器改写、同一匿名消息源、同一组织子品牌或共同错误
上游，都会制造“很多页面都这么说”的假象。另一方面，只检索支持材料会把搜索过程本身
变成确认偏误。

## 决策

1. 每个 claim 的 `EvidenceSearchPlan` 强制包含 support、contradiction、primary source、
   official denial、revision 和 timeline 六类非空查询。
2. Search plan 和 hit 均绑定 `available_at`；只有 decision time 前已检索、未删除且 rights
   为 `ALLOWED`/`LIMITED` 的最新 document revision 可进入证据集。revision 链必须连续、
   predecessor 精确匹配且 availability 不回退；最新 tombstone 不回退旧稿。
3. official denial 只有在绑定的 `OfficialIdentityAssessment` 于 hit 前可用、身份一致、状态为
   `AUTHENTIC` 且命中 polarity 为 `NEGATE` 时成立；普通媒体的“官方否认了”仍只是普通
   二手材料。
4. `EvidenceIndependenceModel` 按显式 provenance 边、相同内容 hash、共同 origin 指纹和
   source independence group 构造依赖连通分量。未知且无依赖信号的来源保持彼此独立，不能
   像旧实现那样全部塞进一个 unknown 桶。
5. `evidence_dependency_score = (evidence_item_count - independent_evidence_count) /
   evidence_item_count`。Truth 层只消费独立数和依赖度；Agent 投票比例不得成为概率。

## 后果

- 十篇来自同一 rumor 的机器改写会得到十个 evidence item、一个独立分量和 `0.9` 依赖度。
- 依赖推断依赖可审计的 hash、origin、ownership 或 graph edge；本阶段不引入黑盒语义聚类，
  以免把措辞相似的独立报道误合并。
- P03 仍是 `DEVELOPMENT` 契约与确定性负控，不提供校准 truth probability 或交易 Alpha。

## 回退条件

如果真实标注集证明确定性信号召回不足，可在后续阶段新增经过校准的相似度候选，但必须保留
当前显式 provenance 路径和逐分量审计输出，不能退回 article count。
