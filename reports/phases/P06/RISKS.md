# P06 风险登记

| ID | 风险 | 当前控制 | 后续触发条件 |
|---|---|---|---|
| P06-RISK-001 | 正式验收按业主要求延期，当前证据只能证明实现和规定验证完成 | 状态保持 `in_progress`，6 个 acceptance 行不改成 verified，不创建 `ACCEPTANCE.md` | 全项目实现完成且业主明确发起统一验收时，重新运行仍适用门禁并写入真实验收时间 |
| P06-RISK-002 | bar、trade/quote 与 L2 都不能在缺少历史队列数据时还原真实 queue position | 每个 Fill 显式携带 `BAR_CONSERVATIVE`、`TRADE_QUOTE` 或 `L2_DEPTH`，报告声明无 queue claim | 获得合规且可归档的逐笔队列数据后，另建版本化模型和一致性 Golden Case |
| P06-RISK-003 | 当前费率、funding、borrow、保证金档位和规则是合成 Golden 政策，不代表任何真实场所 | policy source 明示 synthetic；所有选择按生效区间，缺失时失败关闭 | 引入实际历史政策前必须固定官方来源、归档版本与 point-in-time 合同测试 |
| P06-RISK-004 | 强平是保守档位近似，不模拟真实场所的保险基金、ADL、破产价和并发清算队列 | 近似精度、buffer、penalty 和 reduce-only 成交全部显式记录，并进入权威账本 | 策略依赖场所级清算细节前，新增场所专属 ADR、历史规则和极端行情回放 |
| P06-RISK-005 | NautilusTrader 仍可能发生破坏性 API 变化，Windows wheel 的标准精度上限为 9 位小数 | 版本锁定 `1.231.0`；Nautilus 仅做契约交叉验证，AegisQuant Decimal/账本保持权威 | 升级前先运行固定 QuoteTick 探针和双引擎一致性门，契约变化写 superseding ADR |
| P06-RISK-006 | 本机性能结果只能证明当前 Windows 主机上的有界基准，不是生产 SLA | 报告记录输入规模、耗时、峰值内存、平台、种子和稳定哈希 | 选定部署拓扑后在目标硬件上建立独立容量、并发和长稳门禁 |
| P06-RISK-007 | 本机 Node v24.12.0 低于仓库声明的 24.20.0 | lint、typecheck、unit、build 和 E2E 均实际通过，警告没有隐瞒 | 环境可用时升级到 24.20.0 并重跑前端门 |
| P06-RISK-008 | 既有 Nautilus 回放测试触发 Pandas `Timestamp.utcnow` 弃用警告 | 两套 Python 运行时各 4 条，仅来自上游调用且结果确定 | 上游稳定修复可用后更新锁定契约并移除警告 |

`LIVE_TRADING`、真实账户、私有下单、明文密码、Cookie、验证码和 API Secret 不是待接受风险，
而是持续禁止边界。
