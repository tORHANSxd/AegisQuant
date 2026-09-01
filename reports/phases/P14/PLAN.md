# P14 实施计划

## 目标与边界

P14 在现有事件、账本、风险、研究、情报和 P13 非资金运行证据之上，建立独立、可重建、
可追溯的 Read Model；通过只读 FastAPI `/api/v1` 与版本化 WebSocket 向 Next.js 看板提供
服务端权威口径。Overview 与 `/intelligence` 必须消费同一套实际投影产物，不在浏览器中
硬编码 PnL、风险或事件结论。

Read Model 持久化契约继续使用 P01 锁定的 PostgreSQL，不以 SQLite 或 Mock 冒充数据库
验收。为让本地看板无需常驻数据库即可运行，API 默认只读加载由已验证 P05–P13 工件重建并
带来源哈希的快照；PostgreSQL 的原子重建、检查点和查询则由真实空库迁移与集成测试验证。

本阶段不实现 P15 的全部业务页面，也不增加任何交易写接口。Web、API 和 WebSocket 均无
submit/cancel/amend、真实账户连接、密钥输入或 Live 解锁能力；`LIVE_TRADING` 始终锁定。
开发期正式验收继续按 ADR-0010 后置，不生成 `ACCEPTANCE.md`。

## 实施顺序

1. 固化 P14 需求追踪矩阵与 ADR-0019，记录 FastAPI、Storybook、ECharts、
   Lightweight Charts 的实际稳定版本及契约。
2. 定义 Read Model 事件、记录、质量状态、来源水位、检查点和快照模型；递归拒绝浮点权威
   金额与敏感字段。
3. 实现 account、PnL、position、risk、strategy、model、order、data health 及
   intelligence 基础投影、幂等增量、连续序列检查和失败不污染旧快照的原子重建。
4. 新增 PostgreSQL Read Model 表、迁移和事务性快照替换；验证空库升级、回滚、重建一致性、
   幂等与服务账号只读查询边界。
5. 从 P05–P13 已验证工件重建 P14 开发快照，保留每个来源文件的 SHA-256、时间语义、
   fixture/Paper 限制和非生产声明。
6. 实现 FastAPI `/api/v1` 的 health、overview、account、PnL、position、risk、strategy、
   model、order、data health 与 intelligence 查询；统一游标分页、过滤、错误码和 OpenAPI。
7. 实现 `/ws/v1/stream` 订阅、snapshot、单调 sequence、heartbeat、订阅上限和背压；前端
   检测丢序后必须停止应用增量并通过 REST snapshot 恢复。
8. 固化 OpenAPI 与 WebSocket JSON Schema，生成 TypeScript 类型化客户端并建立差异检查。
9. 将现有 Next.js P00 锁定页升级为 App Router 工作台骨架，根路由跳转 `/overview`，建立
   导航、VIEWER 权限、环境/Live lock/新鲜度状态带及严格 CSP。
10. 建立语义 Design Tokens、深浅色、紧凑/舒适密度、红涨绿跌/绿涨红跌、色盲和高对比模式；
    设置仅保存在设备本地，不包含凭据或交易参数。
11. 建立通用状态容器和组件库；使用一个 Storybook 状态画廊覆盖每个通用组件的正常、加载、空、
    陈旧、降级、断开、错误、窄屏与无障碍场景，避免复制数百份样板 Story。
12. 使用 ECharts 与 Lightweight Charts 的客户端封装实现权益/归因/风险与事件回放图表；所有图表
    同时提供文字摘要和语义数据表。
13. 实现 Overview 和 `/intelligence` 高保真原型，所有金额、风险、来源与事件均来自 API Read
    Model；旧数据、估算和非权威数据必须显式标注。
14. 建立单元、属性、PostgreSQL 集成、OpenAPI、WebSocket、TypeScript、Storybook、视觉回归、
    Playwright E2E、丢序恢复、无障碍、响应式和性能基准。
15. 运行全量 Ruff、Pyright、Python 3.13/3.14、pytest、变异、安全、许可证、前端和 40+ 阶段
    CI；生成 P14 阶段报告、工件清单、状态与一次本地归档。

## 验证标准

- PostgreSQL 空库迁移可升级和完整回滚；同一输入重建得到相同快照哈希和检查点。
- 所有 Read Model 记录都含 `as_of_time`、`projected_at`、`source_watermark`、
  `quality_state` 和来源哈希，且权威金额不使用浮点数。
- API OpenAPI 稳定、分页/过滤/错误码有契约测试；无交易写端点和敏感字段。
- WebSocket sequence gap 会进入断开/恢复状态，REST snapshot 恢复后才继续增量。
- Overview 与 `/intelligence` 从实际 API Read Model 渲染，并明确展示 Paper、Live lock、
  数据截至时间、来源、权威/估算状态。
- Storybook 构建通过；所有已建立的通用组件均进入完整状态画廊。
- Overview 自动性能基准满足 p75 1.5 秒目标，或以失败证据和明确改进项阻断实现完成。

## 明确非目标

- 不实现 P15 的全部页面、复杂下钻、告警确认写操作或研究任务取消。
- 不部署到公网，不连接外部交易所或真实账户，不索取或保存密码、Cookie、验证码、API Secret。
- 不把历史夹具、Paper、回测或研究结果冒充实时市场、收益、Alpha 或容量证据。
- 不运行 12h/24h 正式验收，不生成 P14 `ACCEPTANCE.md`，不解除 Live lock。
