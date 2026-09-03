# V5-P03 实施摘要

P03 已完成双向检索契约、PIT evidence hit 选择、独立性连通分量、独立评审修复和完整
CI，验收结论为 `PASS_WITH_RECORDED_NEGATIVE_RESULTS`。最终工件清单在本摘要完成后
生成并自检。

## 已实现

- `EvidenceSearchPlan` 强制 support、contradiction、primary source、official denial、revision
  与 timeline 六类查询。
- `EvidenceRetrievalHit` 绑定 query hash、document/revision、source identity、policy、rights、
  lineage、官方身份以及 published/observed/available/retrieved/deleted 时间。
- PIT selector 选择 decision time 前最新 revision，排除未来、删除以及
  `UNKNOWN`/`PROHIBITED` rights 命中。
- official denial 不接受自报布尔值，必须绑定 decision time 前可用、身份一致且状态为
  `AUTHENTIC` 的 `OfficialIdentityAssessment`。
- revision history 必须从 1 连续递增、前驱精确匹配且 availability 不回退；最新 revision
  为 tombstone 时整份文档失效，不回退旧稿。
- official denial fail closed：必须是已验证官方身份且 polarity 为 `NEGATE`。
- `EvidenceIndependenceModel` 按 hash、origin、ownership/group 和 provenance edge 计算依赖
  分量；未知且无依赖信号的证据不再被错误折成同一个 unknown group。
- 十篇不同机器改写共享一个 rumor origin 的验收场景得到 10 个 item、1 个独立分量、
  `evidence_dependency_score=0.9`。
- P00/P01/P02 冻结 manifest SHA 迁入 `phase_history`，后续阶段不拿当前工作树回验历史
  manifest。
- 三路独立评审后补强 revision chain、tombstone、official identity assessment 绑定、
  rights unknown fail-closed、graph 直接调用的 PIT/type 校验和实际 provenance edge fixture。
- 修复完整 CI 的生成物因果顺序为 `python-candidate → P00 evidence reset → pytest`，消除
  读取上轮候选状态或对刚更新报告使用过期哈希快照的隐式依赖。
- 最终 CI 59/59 阶段通过：主 Python pytest 741 passed、候选 Python 3.14 为 653 passed，
  security 0 finding，Web build 与三浏览器 E2E 通过。

## 仍未实现

本阶段没有真实互联网检索基准、语义相似度模型、独立性 precision/recall、Truth Council、
概率校准、因果效应或预测/回测结果；更没有可交易 Alpha。
