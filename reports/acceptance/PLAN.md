# P00–P18 系统统一验收计划

## 目标

按 ADR-0010 对 P05–P18 的延期验收执行一次原子化、可复现审计，并把 P00–P04 既有正式验收纳入总览。
验收只判断证据，不补造历史运行，不连接账户，不读取秘密，不改变任何交易、模型或风险实现。

## 需求可追踪基线

- 总任务书 466 条规范性要求：`state/REQUIREMENTS_TRACEABILITY.csv`。
- P05–P18 阶段任务与验收映射：各阶段 `REQUIREMENTS_TRACEABILITY.csv`。
- 本轮最终验收映射：`reports/acceptance/REQUIREMENTS_TRACEABILITY.csv`，预期 93 条验收要求。
- P18 汇总：P00–P17 共 384 条适用需求全部可追溯，`READINESS_EVIDENCE.json` 无遗漏 ID。

## 执行顺序

1. 校验任务书哈希、阶段矩阵、实现/测试/证据路径、阶段 `TEST_RESULTS` 和完整 CI。
2. 保留 P03 已批准的 24h 豁免；保留用户对 P13 12h/24h 的明确不执行决定。
3. 对 P12 真实 Testnet、P16 外部告警及 P18 readiness 使用 fail-closed 判定，不以 fixture 代替。
4. 从 P05 顺序评估；首个 `BLOCKED_EXTERNAL_INPUT` 出现后，后续阶段标记未到达，禁止批量盖章。
5. 生成系统 ACCEPTANCE、SUMMARY、TEST_RESULTS、RISKS、NEXT_ACTIONS、ADR_REFERENCES、WAIVERS 和工件清单。
6. 运行全仓 CI、验收专项测试、安全扫描、双 Python、Web 全链和清单一致性检查。
7. 更新 `state/PROJECT_PHASE_STATE.yaml`，但不把阻断结果改写为 accepted。

## 通过规则

只有 P05–P18 全部适用硬门通过或具有用户明确书面豁免时，才签发缺失阶段 `ACCEPTANCE.md` 并关闭延期
队列。任何外部输入缺口均输出 `BLOCKED_EXTERNAL_INPUT`；P18 `NO_GO` 和 `LIVE_TRADING` 锁不因工程
实现完成而改变。
