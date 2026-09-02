# P15 实施计划

## 目标与边界

完成任务书第 17 章核心工作台：保留 `/overview`，新增 `/live`、`/performance`、`/execution`、
`/strategies`、`/models`、`/market`、完整 `/intelligence`、`/risk`、`/research`、
`/research/intelligence`、`/data`、`/incidents`、`/system` 与安全范围 `/settings`。所有业务数字必须
来自服务端严格 Read Model 和已验证工件；无法证明的实时、生产、Alpha 或容量字段明确不可用。

P15 只实现读取、浏览器本地显示偏好及布局，不增加交易、风险上限、模型发布、凭据、真实账户或 Live
解锁能力。正式验收按 ADR-0010 延后，不执行 12h/24h，也不生成 `ACCEPTANCE.md`。

## 需求追踪

`reports/phases/P15/REQUIREMENTS_TRACEABILITY.csv` 在实施前建立，逐项映射任务书 21 项任务与 7 项
验收条件。开发结束时任务状态更新为 `verified`，正式验收项保持 `in_progress`。

## 实施顺序

1. 扩展 Read Model payload 与确定性 bootstrap，覆盖 fill、execution quality、signal、market、
   model monitoring、research run、incident、system health、reconciliation 和 order trace。
2. 实现服务端 min/max bucket 下采样、游标窗口、ETag/私有重验证缓存和完整只读 REST/WS 主题。
3. 从运行时 OpenAPI 重建 TypeScript 客户端，验证 schema、敏感字段和无写操作契约。
4. 扩展 App Shell 全路由导航，建立可操作的账户/时间/时区/策略/场所筛选、Ctrl+K 命令面板、
   当前视图导出和本地布局保存。
5. 实现所有领域页面、K 线事件/交易回放、指标公式与来源说明，以及订单七段决策链单击下钻。
6. 为每个路由建立 loading/error 边界，完善键盘、焦点、颜色冗余、语义表格和窄屏导航。
7. 建立 Python 单元/属性/契约/集成/变异测试，前端单元、跨浏览器 E2E、视觉回归、大表、长时序、
   API/页面性能预算和安全扫描。
8. 运行完整 P15 CI 与 Python 3.14 候选契约，生成阶段报告、工件清单、状态、实现提交、证据提交和
   一次本地归档。

## 明确非目标

- 不执行正式用户验收或 12h/24h 稳定性验收。
- 不连接真实账户、Testnet 或外部交易网络，不索取或保存任何秘密。
- 不提供 submit/cancel/amend、风险上限编辑、模型发布、事故确认或 Live 解锁。
- 不开始 P16 的 Prometheus、Grafana、Loki、部署、认证或灾备工作。
