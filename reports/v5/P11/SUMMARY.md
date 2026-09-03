# V5-P11 实施摘要

P11 已完成实施并通过“记录负结果”验收：系统具备可重算、不可回填的 Paper/Shadow Forward
证明契约，但真实连续观测仍为 `0` 天，所以结论严格保持 `EXTEND_PAPER / NO_PROMOTION`。开发
夹具只验证合同，绝不冒充 30 天战绩。

## 已实现

- Forward heartbeat 使用连续序号、前序哈希、观测时间和 source PIT 时间形成有界哈希链。
- 预测在 outcome 可用前写入，prediction revision 固定为 0，禁止未来修正和 correction 回填。
- Truth 使用 Brier score 与分桶 ECE，Forecast、Cost 与事件增量分别计算偏差、MAE、方向准确率
  和低估率，避免“正负一抵消，平均值看着挺美”的假校准。
- 独立事件按唯一 independence key 计数；重复键、样本不足、门槛事后降低均 fail closed 或
  `EXTEND_PAPER`。
- 事故日志覆盖完整窗口；每次需重启事故必须有同会话恢复收据，绑定 checkpoint、恢复前后链头、
  最后持久序号、缺口与重复计数。
- Paper/Shadow 必须绑定同一预提交 policy、窗口和预测签名；测试夹具、压缩时间与 backtest 明确
  不能构成 Forward 证明。
- 新增 9 份 P11 顶层版本化 Schema，注册表总数为 197；证据生成、CI、ADR、风险与攻击测试均已
  接线。

## 验收结果

- P11 定向测试 `29 passed`；架构边界加 P11 定向测试 `36 passed`。
- 最终完整 CI `70/70` 通过；主环境 `998 passed / 11 warnings`，候选 Python 3.14 环境
  `653 passed / 11 warnings`。
- 197 份 Schema 无漂移；Web 单元测试 `19 passed`；Bandit findings `0`；安全扫描四项通过，
  `secret_finding_count=0`，未访问真实账户或 secret store。
- 首次 CI 的 B105 状态字面量误报已用精确注释修复，并重新跑完全部 70 阶段，不存在跳门验收。
- 独立复核发现的重复独立事件键、ECE 抵消、跨会话恢复拼接、持久链绑定和资源上界问题均已修复。

## 仍未证明

真实 Paper/Shadow 观察日数为 `0`，没有 30 个连续日历日、真实独立事件、受保护 wall-clock、外部
告警、不可变透明日志或真实预测准确率。测试中构造的 30 天时间戳只验证规则，不证明时间真的经过。
因此 P11 不允许 Canary、订单或 Live，只授权开始 P12 的 readiness 工程；真实运行不足时必须延长
Paper，门槛不许往下拽——不然不是量化，是给结果化妆。
