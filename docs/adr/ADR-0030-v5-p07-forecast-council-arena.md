# ADR-0030：V5-P07 Forecast Council 2.0 与等折 OOS 竞技场

- 状态：Accepted
- 日期：2026-09-03
- 决策范围：MarketStateTensor、Forecast Contract、Capability Matrix、Candidate Gate、Model Arena、Vision Ablation

## 背景

模型名字越响，不代表预测越准，更不代表能上线。TimesFM、Chronos、Moirai、Toto、深度时序、
微观结构和视觉模型的依赖、许可、权重、适用 horizon 与资源消耗各不相同；若让每个候选使用不同
折、不同样本或不同校准集，最后只是在举办“谁更会挑考卷”大赛。P07 需要先建立统一、可审计且
默认闭锁的研究契约，再谈真实数据表现。

## 决策

1. 所有候选统一消费矩形、PIT、内容寻址的 `MarketStateTensor`。每行保存 observed/available time，
   任一输入晚于 decision time 都以 `AQ-FORECAST-MARKET-TENSOR-LOOKAHEAD` 拒绝。
2. 每个 horizon 必须输出九档 return quantile、方向概率、波动分布、high-low、MFE/MAE、barrier、
   tail risk、liquidity/spread/slippage、epistemic/aleatoric uncertainty 与 abstain probability。
3. 校准按 `asset × horizon × regime` 绑定独立 artifact；calibration sample 与 test sample 必须不相交，
   且 artifact availability 不得晚于 forecast as-of time。
4. 能力矩阵完整列出基础、TimesFM 2.5、Chronos-2、Moirai-2、Toto 2.0、监督式、微观结构与可选
   视觉候选。列入 catalog 只表示“可审查的候选”，不表示依赖已安装、权重已下载或生产就绪。
5. 候选进入评估前必须同时通过 capability status、license、dependency、weight hash 和有限资源预算
   门禁；decision 绑定 capability/budget/request hash。Zero-shot 永久带
   `AQ-FORECAST-ZERO-SHOT-NO-PROMOTION` 限制。
6. Model Arena 对每个候选强制相同 split hash、dataset manifest、calibration artifact、时间边界及
   train/calibration/test sample IDs。prediction artifact 不得跨候选或跨折复用。
7. Champion 只按 `asset × horizon × regime` 产生，必须超过冻结的 baseline 改善下限；不存在全市场
   通吃的 universal model 假设。失败、abstain 和无增量结果保留且不得被选中。
8. Vision 必须执行 Numeric-only、Vision-only、Numeric+Vision 三方 OOS 消融；达不到冻结增量下限
   就淘汰。P07 不为此引入图像模型依赖或下载权重。
9. 竞技场权重或选择只能接触 validation/calibration/forward 证据，不打开 Final Holdout。P07 的
   确定性数字只用于验证契约和门禁，不能宣称真实准确率、Alpha、收益或 Promotion。
10. P08 才负责 Market-only 与 Event-conditioned forecast 的增量消融；P07 不提前把 P06 因果估计
    塞进方向模型，也不使用固定 `HORIZON_SCALE` 冒充事件影响路径。

## 后果

- 不同模型族可以在同一接口下被公平拒绝、评估和比较，且能力/数据/校准/预测工件均有哈希血缘。
- 未安装的大模型保留为诚实的 adapter/dependency/license 状态；避免为了“看着先进”下载一座依赖山。
- 当前只证明工程约束生效。真实公网数据 OOS、成本后经济性、Paper/Shadow/Testnet 与 Final Holdout
  仍需后续阶段单独验收。

## 回退条件

若真实数据表明当前 horizon、regime、metric 或 baseline 门槛不适用，应新增版本化 spec、schema 与
ADR，并保留旧竞技结果。不得通过改变某个候选的折、回填未来数据、复用 prediction artifact、删除
失败记录、降低 vision 增量门槛或打开 Final Holdout 来“修漂亮”排名。
