# P08 实施总结

P08 的工程实现与规定的非实机验收验证已完成，正式验收按项目业主决定延期。阶段保持
`in_progress`，未生成 `ACCEPTANCE.md`，未写入 `accepted_at_utc`，也未开始 P09。

## 已交付

- 机器可读 Hypothesis、显式审批队列、资源预算、追加式哈希链实验事件、内容寻址工件、
  MLflow 本地投影和保留成功/失败/剪枝结果的 Optuna 搜索。
- LightGBM、CatBoost、XGBoost、轻量 TCN、Patch Transformer 和概率预测统一契约；
  split conformal、七类 abstain、严格 OOF stacking、状态门控及 drift/OOD 降级。
- Chronos-2、Moirai 2、TimesFM 3、Kronos 插件清单。Chronos-2-small 完成固定 revision、
  权重 SHA-256 和 CPU 有限推断；研究或静态分析受限模型没有执行。
- Model Card、Champion/Challenger alias 与人工晋升边界，以及同 split、成本、预算和种子的
  Model Council。`linear-fused` 胜出，所有复杂候选均被淘汰，没有复杂度特权。
- 无工具的结构化 LLM Provider、RAG/Source Policy/提示词注入门禁、九类事件专家加 Policy 与
  Arbiter、Claim/Event Graph、冲突与状态迁移、多尺度 EventImpactForecast。
- 2024-01-31 FOMC 一手事件与 Binance Vision BTCUSDT 公共行情的 point-in-time 历史回放；
  事件与融合路径因证据不足而 abstain，报告不声称因果关系或 Alpha。

## 安全与边界

`LIVE_TRADING=false` 且 `live_trading_locked=true`；未连接真实交易账户、未认证、未下单，
未索取或写入密码、Cookie、验证码或 API Secret。AI 只能提出 Proposal，不能自批、改模型
alias、打开最终 holdout 或获得工具/交易能力。最终 holdout 仍为 `LOCKED`，调用次数为 0。

当前主机没有 NVIDIA GPU。CPU 上限、预算拒绝和可恢复 OOM 契约已经验证，但 4070 Ti 实机
上限属于正式验收项，继续保持未验收；没有拿空气显卡演戏。完整测试结果和提交绑定分别见
`TEST_RESULTS.json` 与 `ARTIFACT_MANIFEST.json`。

## 验证结果

- 完整 CI：29/29 阶段通过。
- Python 3.13.15：360/360 测试通过；Python 3.14.7 隔离契约：323/323 通过。
- P08 关键变异：8/8 被杀死，得分 1.0，高于 0.90 门槛。
- Secret 命中 0、Python/JavaScript 依赖审计通过、Python 未知许可证 0；完整 `mlflow`
  Gateway 分发未安装，使用通过 SQLite/Registry alias 契约的 `mlflow-skinny`。
- 第一轮完整 CI 暴露 Windows 原子目录发布的瞬时 `WinError 5`；加入 3 次有界重试与回归测试后，
  第二轮完整 CI 全绿。失败记录没有被当成最终成功偷偷抹掉。

实现提交：`aff9ae4224bd512c7ad95e25b0da0a637041e4b7`。
