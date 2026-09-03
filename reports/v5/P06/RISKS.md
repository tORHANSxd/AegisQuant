# V5-P06 风险

1. **诊断通过不等于无混杂。** pre-trend、balance、overlap 和 placebo 只能击穿部分坏设计，无法
   证明 unconfoundedness、SUTVA、稳定处理定义或无同时冲击。
2. **单事件 DID 没有可信采样方差。** 当前返回点估计但不伪造标准误/置信区间；需要多事件、
   cluster-aware bootstrap 或合适的 randomization inference 才能谈不确定性。
3. **合成控制依赖 donor pool。** donors 必须在 treated decision 前完成 outcome，避免后见之明；
   但历史 donor 与当前制度环境是否可交换仍需真实数据验证。
4. **Overlap 只是必要条件。** 同时存在 treated/control 且 propensity 落在固定边界，不代表高维
   covariate 已充分重叠，也不证明 propensity 估计正确。
5. **Nuisance lineage 依赖外部工件。** observation 绑定 model hash、training cutoff、feature hash
   和 availability；这些 hash 的真实性仍依赖内容寻址存储与 Manifest，而不是模型对象凭空证明。
6. **Placebo 有多重检验风险。** 当前三类检验使用固定经验 p-value 门槛；真实研究必须预注册事件
   family、窗口与校正策略，禁止挑最好看的 placebo。
7. **事件时点可能内生。** 新闻发布时间、市场发现时间与交易响应时间可能相互作用；timestamp
   placebo 不能自动修复 endogeneity。
8. **当前数字全是 fixture。** 已知反事实上的 `1.0/1.5` 效果只证明实现能复算，不证明 BTC、
   宏观事件或任何资产存在同等效应。
9. **工作树 Manifest 不是外部不可篡改锚。** 历史 SHA 与状态交叉绑定可发现普通漂移，但不能
   替代签名、受保护远端或透明日志。
10. **没有交易证据。** P06 没有真实 OOS 准确率、成本后净收益或 forward trading；任何 Alpha、
    Paper、Shadow、Testnet、Canary 或 Live 表述都越界。
11. **优化器收敛标志不是识别证据。** 当前 projected-gradient 以权重变化判断数值收敛，未单独
    输出 KKT/梯度残差；最终因果门禁仍必须依赖 pre-fit 与其他诊断，不能把 `converged=true`
    当成模型有效。
12. **匹配尺度是明确但有限的工程选择。** 当前距离使用 control-only population standard
    deviation，而 balance 使用 pooled 口径；真实研究需预注册尺度并做敏感性分析，禁止事后
    选择最有利口径。
