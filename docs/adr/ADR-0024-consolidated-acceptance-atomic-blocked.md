# ADR-0024：统一验收的原子提交与外部硬门阻断

- 状态：Accepted for audit
- 日期：2026-09-02
- 决策范围：P05–P18 统一正式验收

## 背景

ADR-0010 按项目业主要求把 P05–P18 的正式验收推迟到全部工程实现完成之后。现在 P18 工程实现和
完整 CI 已完成，业主确认开始下一环节，并继续要求不执行 12h/24h 验收。统一验收不能倒填历史，
也不能把离线契约、逻辑周期或本地告警当作真实外部运行证据。

任务书明确规定：没有本地秘密库 Testnet 凭据时，P12 可以完成模拟和契约实现，但真实 Testnet 验收
必须标记 `blocked`。P16 的外部用户告警送达同样没有运行证据。P18 已正确输出 `NO_GO`，没有策略、
账户、合约或非零资本范围。

## 决定

1. 统一验收采用原子提交。先完整评估所有延期阶段的内在证据，但只有整条 P05–P18 依赖链通过时才
   一次性签发缺失的阶段 `ACCEPTANCE.md` 并清空延期队列，避免部分改写状态后留下双重权威。
2. P05–P11 当前标记为 `READY_NOT_ISSUED_ATOMIC_AUDIT`。这表示内在条件满足，不等于已经正式
   accepted，也不修改其历史阶段证据。
3. P12 在 `P12-A01` 停止，结论为 `BLOCKED_EXTERNAL_INPUT`。不得请求秘密值，不得连接真实账户，
   不得用模拟 Testnet 或 fixture 伪造真实网络通过。
4. P13–P18 正式顺序标记 `NOT_REACHED_DEPENDENCY_BLOCKED`。仍可记录内在审查结果，但不能越过 P12
   签发验收。
5. 项目业主已明确决定不执行 12h/24h，登记 `P13-WAIVER-001`。该豁免只允许未来以书面豁免状态
   处理，不把逻辑 10,080 周期转换为合格墙钟证据。
6. P16 外部告警 `P16-A03` 保持 `BLOCKED_EXTERNAL_INPUT`；目标 Linux 和异机备份继续作为 P18
   readiness 阻断，均无隐式豁免。
7. 系统当前只可表述为“非 Live 工程实现完成、正式生产验收阻断”。P18 `NO_GO`、有效资本 0、真实
   订单能力 false 和 `LIVE_TRADING` 锁必须保持。

## 证据

- `reports/execution/P12_TESTNET_CAPABILITY.json`
- `reports/runtime/P13_STABILITY_EVIDENCE.json`
- `reports/observability/P16_ALERT_EVIDENCE.json`
- `reports/live_readiness/READINESS_EVIDENCE.json`
- `reports/acceptance/REQUIREMENTS_TRACEABILITY.csv`
- `reports/acceptance/SYSTEM_ACCEPTANCE.json`

## 后果与回退

- 好处：验收结果与任务书、真实外部能力和历史证据一致，避免“代码全绿所以实盘也绿了”的荒唐跳跃。
- 代价：在用户自行配置 Testnet 引用并完成真实运行证据前，整个统一验收不能关闭。
- 回退条件：若审计脚本或映射有误，删除未签发的系统验收工件并修复后重跑；既有 P00–P04 验收、
  P03 豁免、P05–P18 实现提交和 `LIVE_TRADING` 锁不得被回退或弱化。
