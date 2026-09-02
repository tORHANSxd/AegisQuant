# 系统统一验收豁免登记

| Waiver | Requirement | 状态 | 说明 |
|---|---|---|---|
| P03-WAIVER-001 | P03-A01 | 已应用 | 不执行真实连续 24 小时公共流；不得声称生产采集 SLA。 |
| P13-WAIVER-001 | P13-A01 | 已获业主明确决定，尚未消费 | 不执行 12h/24h；逻辑周期保持 non-qualifying。 |

P12 真实 Testnet、P16 外部告警、目标 Linux、异机备份和 Canary 硬门均没有豁免。它们必须保持
`BLOCKED_EXTERNAL_INPUT` 或 `NO_GO`，不能顺手塞进豁免表蒙混过关。
