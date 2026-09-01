# P03 验收记录

## 决定

P03 以 `accepted_with_waiver` 关闭。验收对象为实现提交
`8a2a8971c6ca8de40711bba392a37486b5e5799c`。这不是“24 小时通过”：项目业主明确
豁免 `P03-A01`，该项结果为 `WAIVED`，其余 19 项要求均为 `VERIFIED`。

## 阶段验收项

| 验收项 | 结果 | 证据 |
|---|---|---|
| P03-A01：真实连续 24 小时公开流无无法解释的 gap | WAIVED | `ADR-0007`、`BINANCE_SOAK_ATTEMPT_SUMMARY.json`；不存在合格 `BINANCE_24H_SOAK.json` |
| P03-A02：断网后重建订单簿与 watermark | PASS | 生命周期、强制断开、快照重建与恢复契约测试 |
| P03-A03：重复、乱序、迟到行为明确 | PASS | 订单簿状态机、幂等、晚到和 gap 测试 |
| P03-A04：按时间查询 instrument rule 快照 | PASS | PIT instrument 规范化与查询测试 |
| P03-A05：数据具有来源时间和质量字段 | PASS | Silver schema、模型与规范化测试 |
| P03-A06：CI 离线且外部交互使用 fixture | PASS | 19/19 本地 CI 门与公共网络禁用测试 |
| P03-A07：适配器没有账户和订单权限 | PASS | 公共端点 allowlist、无认证、无订单能力安全测试 |

## 二十四小时尝试事实

| 尝试 | 实际时长 | 结果 | 结论 |
|---|---:|---|---|
| P03-SOAK-ATTEMPT-001 | 34,949.941 秒 | 外部中断 | 未达到 86,400 秒，没有最终合格证据 |
| P03-SOAK-ATTEMPT-002 | 11.609 秒 | HTTP 451 | USDⓈ-M REST 快照不可达，明确失败 |

两次尝试不得拼接，不得外推，也不得改名冒充通过。说白了，差一秒都不算，更别说第一回
只跑了约 9 小时 42 分；这块账必须硬。

## 其余硬门

| 硬门 | 结果 | 说明 |
|---|---|---|
| 完整 CI | PASS | 19/19 门通过 |
| Python 3.13 | PASS | 159 passed，0 failed，0 skipped |
| Python 3.14 | PASS | 123 passed，0 failed，0 skipped |
| 安全与供应链 | PASS | Bandit/秘密扫描 0 发现；双生态审计、SBOM、许可证检查通过 |
| 公开数据边界 | PASS | 只允许 Spot/USDⓈ-M 官方公共市场端点；无账户、订单、认证或私有 API |
| `LIVE_TRADING` 锁 | PASS | 配置、注册表、导入副作用和安全回归测试均保持锁定 |
| P04 阶段边界 | PASS | P03 证据收口期间未实现 P04 |

## 限制

本验收不授予生产采集 SLA，不证明当前区域的 USDⓈ-M REST 可达，不允许真实账户或任何
交易操作。若未来需要上述能力，必须按新阶段要求和新 ADR 重新验证，不能消费本次豁免
当万能通行证。
