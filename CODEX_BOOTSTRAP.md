# Codex 启动契约

每次工程执行前必须按以下顺序读取：

1. `AegisQuant_v5.0_Truth_Causal_AI_Forecast_Codex_Master_Plan.md`；
2. `state/V5_PROJECT_STATE.yaml` 与 `state/V5_OPEN_RISKS.yaml`；
3. `reports/v5/<phase>/PLAN.md`、`RISKS.md` 与 `NEXT_ACTIONS.md`；
4. 仅在核对旧实现时读取 v3.1 规格、`state/PROJECT_PHASE_STATE.yaml` 和旧追踪矩阵。

只执行 v5 状态指定的阶段。先形成可追踪计划，再修改；运行阶段规定的完整测试并
生成证据。验收失败时把状态标记为 `failed` 或 `blocked` 并停止，不能进入下一阶段。
旧 v3.1 状态不得覆盖或推进 v5 状态。

安全硬约束：研究、CI 和 Web 进程不能持有交易秘密；未经过独立的未来人工解锁流
程，任何代码路径都不能发送真实订单。V5 各阶段在正式 Promotion Gate 前始终保持 Live
锁定。
