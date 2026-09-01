# P03 开放风险

P03 带一项业主豁免关闭，因此风险不是“测试都绿了就没事”。绿灯证明实现契约没烂，不能
凭空补出那 14 个多小时，更不能把 HTTP 451 当网络抖了一下糊弄过去。

| ID | 级别 | 风险 | 当前约束 |
|---|---|---|---|
| P03-RISK-001 | high | 24 小时 Binance 双流验收被明确豁免 | 状态固定为 `accepted_with_waiver`；禁止声称 24 小时稳定；生产采集 SLA 前必须重跑不少于 86,400 秒 |
| P03-RISK-002 | medium | 当前网络区域访问 USDⓈ-M REST depth 返回 HTTP 451 | 不绕过区域控制；若恢复验收，只能在法律与 Binance 条款允许的区域使用官方公共端点 |
| P03-RISK-003 | medium | Binance 公共端点、字段和流路由会漂移 | fixture 回放、Changelog watcher、未知字段保留和公共契约 smoke 持续阻断升级 |

继承风险包括 NautilusTrader Beta/Windows 支持边界、pandas UTC 弃用提示、PyArrow stubs
版本差、磁盘容量、独立备份未配置和远程 GitHub Actions 未执行。机器可读全集位于
`state/OPEN_RISKS.yaml`。

任何账户访问、凭据要求、私有 API、订单能力或 `LIVE_TRADING` 解锁都不属于本豁免；一旦
出现必须直接失败并停止阶段推进。
