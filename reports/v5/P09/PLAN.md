# V5-P09 实施计划

## 目标

在 P07/P08 Forecast Council 上实现只读 Meta-Reasoner、独立 Skeptic、统计学习驱动的动态
stacking、PIT regime router，以及按 asset×horizon×regime 维护的 adaptive / distribution-aware
conformal 覆盖率监控。所有非确定性建议只能收紧或触发 abstain，不得生成订单或覆盖统计门禁。

## 实施范围

1. 用内容寻址 `ReasoningContext` 绑定 Truth、证据图、事件、预测、regime、可靠度、校准、OOD、
   price-in、成本、组合与风险状态，并预提交两条评审路径各自的 prompt/model revision hash。
2. Meta-Reasoner 只输出冲突、反事实问题、权重上限建议、abstain 建议和解释；结构中不存在订单
   方向、数量、场所或下单能力。
3. Skeptic 使用不同 prompt 与模型 revision，只共享上游事实快照，不共享 Arbiter 最终输出；高/
   严重发现必须阻止新增风险。
4. Council disagreement 从成员预测重新计算，方向冲突或区间超过政策阈值时 abstain。
5. 动态 stacking 复用 OOF capped weights、simplex 可行性检查和 maximum-step smoothing；权重证据
   白名单只允许 validation、calibration、forward，每次至少需要 validation/calibration，forward 仅在
   PIT 工件真实可用后附加，禁止 Final Holdout，且按 asset×horizon×regime 路由。
6. OOD、UNKNOWN regime、低数据质量、不确定 Truth 或低模型可靠度均 fail closed。
7. 时间序列 conformal 只允许 adaptive / distribution-aware 方法；distribution-aware nonconformity
   按每条预测区间 scale 归一化，并作用于新预测自己的 base scale。滚动 coverage window 必须绑定
   dataset、模型、校准、结果可得时间与唯一样本，禁止机械假设 exchangeability。
8. undercoverage、过度覆盖、样本不足和窗口过期产生显式 RECALIBRATE/DEGRADE/ABSTAIN 动作。
9. 新增版本化 Schema、确定性阶段证据、ADR、CI/Manifest/state 接线和攻击测试。

## 验收门槛

- Meta-Reasoner 与 Skeptic 不能发布订单，且边界会重新验证 `model_construct` 伪造；
- 分歧由成员预测重算并能触发 abstain；
- OOD 与未知 regime 能触发 abstain；
- calibration drift 有显式 fail-closed 动作；
- interval coverage 按 cell、滚动窗口和 PIT 结果可得时间监控；
- Final Holdout、Alpha Promotion、订单、真实账户和 Live trading 继续锁定；
- 完整 CI、独立复核、内容寻址 Manifest 全部通过后才授权 V5-P10。
