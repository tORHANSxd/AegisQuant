# V5-P05 实施摘要

P05 已完成实施并通过阶段验收：事件从零散 claim/cluster 提升为可回放的
`CanonicalEvent`，Surprise、叙事扩散与市场反射均绑定决策时点，方向影响路径统一经过
fail-closed 门禁。所有证据仍是确定性 `DEVELOPMENT` fixture，不声称真实预测准确率。

## 已实现

- EventCluster 加固了证据唯一性、support/contradiction 隔离、官方确认子集、独立来源计数、
  状态与官方证据一致性，并禁止自引用 supersession。
- 内容管线只选择决策时点前已观察的最新 revision；未来内容、重复 revision、revision 时间倒退、
  未来修改/删除知识均被拒绝。
- 官方 `FACT + AFFIRM` 才能形成 confirmed；rumor 即便来自已验证账号也不能偷渡确认，官方否认
  单独形成 denied。
- `TimedEventValue` 分别保存 actual、consensus、whisper，`EventSurprise` 从哈希绑定的同一快照
  重算数值与方向，CanonicalEvent 不接受伪造的独立 surprise 标量。
- Narrative Diffusion 保存首次来源、首次已验证来源、独立来源/平台/语言数量、传播速度以及价格和
  成交量响应延迟，所有字段均有 source hash 与 availability 约束。
- Market Reflection 使用十个必需维度、固定 Decimal 权重、24 小时最大新鲜度和版本化 `0.80`
  bootstrap 阈值。缺失/过期输入返回 `score=null + DEGRADED`，不把未知伪装成零。
- high price-in、rumor、反射不足和无 canonical gate 的旧路径全部 abstain 并把方向收益归零；
  low price-in confirmed 也只是 `RESEARCH_PROPOSAL_ONLY`，下单始终关闭。
- 新增十份 P05 事件契约；`EventImpactForecast` 升级为 v2 且要求显式迁移，历史 v1 schema 保留。

## 验收结果

- P05 定向测试 `25 passed`，相关历史兼容集 `99 passed`。
- 最终完整 CI `64/64` 通过；主环境 `776 passed / 11 warnings`，候选 Python 环境
  `653 passed / 11 warnings`，三浏览器 E2E `19 passed / 2 skipped`。
- 安全扫描全部通过，`secret_finding_count=0`，未访问真实账户或 secret store。
- 三项独立评审发现并促成修复未来 Surprise 泄漏、伪造 gate 阈值绕过以及 revision 生命周期
  倒退；攻击测试已固化。
- P15 可复现快照哈希变化导致的六张黄金图漂移已更新，未放宽截图容差，最终 E2E 通过。

## 仍未证明

没有真实 PIT 事件语料、真实 price-in 标签、因果效应、OOS 预测准确率、净收益或 forward trading
证据。当前权重和阈值只证明工程门禁可执行，不证明其数值在市场上已校准。
