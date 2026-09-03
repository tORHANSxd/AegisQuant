# ADR-0029：V5-P06 事件响应数据集与因果诊断门禁

- 状态：Accepted
- 日期：2026-09-03
- 决策范围：Event Response Dataset、Matched Controls、Synthetic Control、AIPW、Placebo、Causal Claim Gate

## 背景

事件之后价格上涨不等于事件造成了上涨。市场状态、共同冲击、资产 beta、事件选择时点以及后来
才可见的修订，都能制造一条挺唬人的假因果曲线。P05 只把事件身份、Surprise 和 price-in 上下文
做成了可回放事实；P06 必须再回答反事实问题，并且在识别条件不足时明确闭嘴。

## 决策

1. `EventResponseRow` 同时保存事件 revision、决策时点前的特征可用时间、未来标签窗口、五档收益、
   波动/流动性/tail/MFE/MAE 及全部 lineage hash。标签必须从决策时点之后开始，完整覆盖七天，且
   outcome 在数据集 `as_of_time` 前已知。
2. 生产构造入口从一个 `CanonicalEvent` 注入事件 ID、revision、hash、event type、available time、
   Truth、保守 source quality、novelty、market reflection 与 Surprise 标量；调用方不得覆盖这些
   字段。同一 revision ID 在数据集中不得绑定到不同事件身份。
3. 历史状态匹配只使用处理时点之前的候选；默认要求同资产、同 regime，且候选 outcome 在处理
   时点已知。匹配按标准化距离、state ID 确定性排序，并使用 caliper fail closed。
4. 短期估计提供 matched difference-in-differences；四小时以上重大事件提供 simplex 约束的
   synthetic control；另提供使用决策时点前 nuisance prediction 的 AIPW。P06 不引入新的因果库，
   合成控制以 NumPy 投影梯度实现，避免为一个受控优化问题堆依赖城堡。
5. 因果诊断必须包含 pre-treatment fit、pre-trend、covariate balance、propensity overlap、event
   timestamp placebo、asset placebo 和 treatment permutation。报告保存原始路径/矩阵/分数并重算
   指标，不能只信调用方提交的 `passed=true`。
6. P06 仅接受精确版本的默认诊断 policy；阈值、placebo 数量或 policy payload 被放宽时拒绝解析。
   pre-trend、placebo、overlap、balance、control count 或识别假设任一不合格即禁止 causal claim。
7. 即使全部诊断通过，`DEVELOPMENT` 证据也只能得到 `DEVELOPMENT_ONLY`，不得宣传真实因果、
   Alpha 或准确率。`CausalEffectEstimate` 永久固定不触发 Alpha Promotion、订单或 Live trading。
8. 相关性、预测增量和因果效应分别报告。P06 没有执行真实公开 PIT 回测，因此不会拿 fixture 的
   漂亮数字冒充市场结论。

## 后果

- P06 提供可复算的反事实研究骨架与失败记录，不再把 event-after-return 当成因果估计。
- 阈值和结果 payload 的自洽伪造会被模型校验拒绝；未来 policy 变化必须新版本、新 schema、新 ADR。
- 当前确定性样本只证明工程与门禁行为，真实可识别性、预测增量和成本后收益仍未证明。

## 回退条件

若真实 PIT 数据显示匹配、synthetic control、AIPW 或当前诊断 policy 不适用，只能新增估计器/
policy 版本并保留失败证据；不得删除 negative result、回填未来事件修订、放松 placebo/pre-trend
门禁，或把未识别估计接入订单路径。
