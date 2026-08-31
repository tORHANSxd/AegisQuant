# Codex 启动契约

每次工程执行前必须按以下顺序读取：

1. `docs/spec/AegisQuant_Master_Taskbook_v3_1.md`；
2. `state/PROJECT_PHASE_STATE.yaml`；
3. 当前阶段的 `PLAN.md`、`RISKS.md` 与 `NEXT_ACTIONS.md`；
4. `state/REQUIREMENTS_TRACEABILITY.csv` 中当前阶段和 `ALL` 约束。

只执行阶段状态指定的阶段。先形成可追踪计划，再修改；运行阶段规定的完整测试并
生成证据。验收失败时把状态标记为 `failed` 或 `blocked` 并停止，不能自行进入下一
阶段。

安全硬约束：研究、CI 和 Web 进程不能持有交易秘密；未经过独立的未来人工解锁流
程，任何代码路径都不能发送真实订单。P00 始终保持 Live 锁定。
