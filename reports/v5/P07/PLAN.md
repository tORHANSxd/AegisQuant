# V5-P07 — Forecast Council 2.0

- Evidence Tier: `DEVELOPMENT`
- Alpha Promotion Eligible: `false`
- Live Trading Locked: `true`

## 规格边界

本阶段严格覆盖 v5 SSOT 的 TimesFM 2.5、Chronos-2、Moirai-2、Toto 2.0、监督式时序专家、
微观结构候选、可选视觉候选、`MarketStateTensor`、完整多 horizon 预测输出、能力矩阵、候选门禁及
等折 OOS Model Arena。P08 的事件条件预测增量、真实公开数据准确率、Final Holdout、Forward 与任何
交易 Promotion 不在本阶段冒领。

## 实施顺序

1. 建立矩形、PIT、内容寻址的市场状态张量和 asset/horizon/regime 校准工件。
2. 强制每个 horizon 输出 return distribution、方向概率、波动、range、MFE/MAE、barrier、tail、
   流动性/点差/滑点、不确定性与 abstain probability。
3. 建立 24 个候选的显式能力目录，区分 catalog、adapter、dependency、license 与 runnable 状态。
4. 在评估前执行 license/dependency/weight/resource budget fail-closed 门禁，并绑定输入哈希。
5. 用完全相同的 OOS 折、样本、dataset 与 calibration artifact 比较候选；按
   `asset × horizon × regime` 选择研究 Champion。
6. 执行视觉三方消融，保留失败/abstain/无增量结果，并拒绝 lineage splice 与 prediction reuse。
7. 生成版本化 Schema、确定性证据、攻击测试、完整 CI、独立评审和内容寻址 Manifest。

## Acceptance

- 必须存在完整 capability matrix，并明确所有 foundation models 仅为 candidate。
- 所有候选必须使用相同 OOS folds；任何数据、校准、时间或样本身份差异都 fail closed。
- Zero-shot 结果不得等同 Promotion；不存在单一 universal model 假设。
- Champion 必须按 asset/horizon/regime 选择，并保留 baseline、失败与负结果。
- Vision 无 material OOS increment 时必须淘汰。
- 所有输出保持 `DEVELOPMENT`、`NO_PROVEN_ALPHA`、订单关闭与 Live 锁。
