# V5-P09 验收记录

- Evidence Tier: `DEVELOPMENT`
- Alpha Promotion Eligible: `false`
- Decision: `PASS_WITH_RECORDED_NEGATIVE_RESULTS`
- Real-world Forecast Accuracy Claimed: `false`
- Final Holdout Opened: `false`
- Order Submission Enabled: `false`
- Live Trading Locked: `true`

P09 已完成 Forecast governance 契约：只读 Meta-Reasoner、独立 Skeptic、Council 分歧重算、动态
stacking、PIT regime router、adaptive/distribution-aware conformal 与覆盖漂移动作均已落地。最终
完整门禁 `68/68` 通过：主环境 `933 passed / 11 warnings`，候选 Python 3.14 环境
`653 passed / 11 warnings`，174 份 Schema 工件无漂移，Web lint/typecheck/unit/Storybook/build/E2E
全部通过，安全扫描 `secret_finding_count=0`。P09 定向测试 `40 passed`。

Meta-Reasoner 与 Skeptic 只允许 `RESEARCH_RECOMMENDATION_ONLY`，结构中没有方向、数量、场所或
下单能力。两条评审路径的 prompt 与模型 revision 由 `ReasoningContext` 预提交且必须不同，输出
必须逐项匹配；HIGH/CRITICAL Skeptic finding 必须阻止新增风险。Council 分歧、最终 abstain 和
coverage 指标均从输入重算，调用方伪造布尔值或重算普通哈希不能绕过语义校验。

动态 stacking 的证据来源白名单为 validation/calibration/forward，每次至少要求 validation 与
calibration；P09 没有伪造尚不存在的 forward 工件，Final Holdout 始终禁止。路由按
asset×horizon×regime 绑定，OOD、UNKNOWN、低数据质量、不确定 Truth、低可靠度、未来 proposal、
cell/model splice、不可行权重上限或权重步长越界均 fail closed。

distribution-aware conformal 使用每条历史预测区间 half-width 归一化 nonconformity，并将校准的
scale multiplier 应用于新预测自身的 base half-width；零 scale 被拒绝。滚动窗口绑定 dataset、模型、
校准工件、唯一 sample、prediction time、outcome availability 与 decision time，并对欠覆盖、过度
覆盖、样本不足和窗口过期生成显式 RECALIBRATE/DEGRADE/ABSTAIN 动作。该确定性 DEVELOPMENT
fixture 不构成真实覆盖保证。

三项独立只读复核覆盖契约绕过面、数学边界和治理/阶段接线。复核发现的评审模型未预绑定、
distribution-aware 名称与实现不完全相符、权重 cap 可行性缺口、浅冻结哈希字典与策略边界测试不足
均已修复。关于 forward 的歧义按主计划“只能根据 validation/calibration/forward 更新”解释为来源
白名单：forward 只能在真实 PIT 工件存在后加入，不能为了满足字面枚举伪造证据。

完整 CI 初轮暴露出 16 个哈希映射高熵误报，并连锁导致安全、候选 Python 与主 pytest 失败。修复
没有放宽 secret scanner，而是把可变哈希字典改成不可变、显式的 kind/source + artifact_sha256
绑定记录；安全复扫归零，第二轮完整 CI 全绿。

阶段按记录负结果通过并授权开始 `V5-P10`。P09 governance 尚未成为 execution translator 的必选
输入，内容哈希也不能证明外部工件真实性；没有真实公网 PIT OOS/Forward、Final Holdout、Alpha、
Paper、Shadow、Testnet、真实账户或实盘授权。订单提交与 Live trading 继续锁定。
