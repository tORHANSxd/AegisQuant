# P14 实施总结

P14 已建立独立、可重建的只读查询层。系统从 P05–P13 的已验证工件确定性生成 12 类投影、
15 条 Read Model 记录和逐投影检查点；每条记录都携带时间语义、来源水位、质量状态、来源工件
及 SHA-256。权威金额保持十进制语义，投影边界拒绝浮点数与敏感字段，失败重建不会污染上一份
有效快照。

PostgreSQL 18.6 实库完成空库迁移、完整回滚、事务性替换、幂等与只读服务角色验证。FastAPI
仅提供 `/api/v1` GET 查询和 `/ws/v1/stream` 非权威增量；没有 submit、cancel、amend 或账户写
端点。WebSocket 具备单调序列、topic 白名单、origin 白名单、固定队列与背压断开，丢序后必须通过
REST snapshot 恢复。

OpenAPI 由实际应用生成，`@hey-api/openapi-ts` 生成 16 个 TypeScript 客户端文件并通过差异检查。
Next.js 16 工作台实现 `/overview` 与 `/intelligence`，固定 `VIEWER · READ ONLY`、RESEARCH 环境和
`LIVE TRADING LOCKED` 标识；CSP 使用每请求 nonce。24 个通用组件进入 10 状态 Storybook 画廊，
图表同时提供文字摘要与语义数据表，Playwright 覆盖视觉基线、响应式和性能。

安全审计发现并消除了两条开发依赖风险：`js-yaml` 统一锁到 4.3.2，Storybook 从会引入无修复版
`image-size` 的 Next.js 框架切换到官方 React Webpack 5 框架及 SWC 编译器。最终 JavaScript、
Python 依赖审计和秘密扫描均为零发现，许可证清单无未知项。

锁定的 Node 24.20.0 / pnpm 11.24.0 环境下，完整流水线 44/44 通过：Python 3.13 为 602 项通过，
Python 3.14.7 隔离候选环境为 563 项通过，P14 变异 9/9 全部击杀；Web 单元测试 16 项、E2E 4 项
通过，Overview 本地生产构建 p75 为 92ms，低于 1500ms 门限。

按业主决定，本阶段没有运行 12h/24h 墙钟验收，也不生成 `ACCEPTANCE.md`。上述结果证明 P14
实现和自动化门禁完成，不等于正式验收；没有连接真实账户、Testnet 或交易场所网络，没有请求或
写入明文秘密，`LIVE_TRADING` 继续锁定，P15 尚未开始。
