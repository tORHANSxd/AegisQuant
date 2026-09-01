# ADR-0019：P14 Read Model、API、实时流与看板契约

- 状态：Accepted
- 日期：2026-09-02
- 阶段：P14

## 背景

P14 要把账本、风险、执行、研究和事件情报投影成独立查询模型，并提供稳定 REST、实时增量及
Next.js 看板基础。任务书中的依赖版本已经随时间变化；同时，网页不能查询交易核心库、访问交易所、
保存凭据或获得交易写能力。

## 决定

1. Read Model 持久化继续使用 ADR-0004 锁定的 PostgreSQL/SQLAlchemy/Psycopg 技术栈。
   新迁移建立投影记录和检查点表；空库升级、完整回滚及原子重建必须在真实 PostgreSQL 18.6 上验证，
   禁止以 SQLite 或 Mock 代替。
2. 每条投影记录固定包含 `as_of_time`、`projected_at`、`source_watermark`、
   `quality_state`、来源工件 SHA-256 和内容 SHA-256。权威金额保持十进制字符串；投影入口递归拒绝
   Python/JSON 浮点数和 password、cookie、secret、token、api_key 等敏感键。
3. P14 本地 API 默认加载由已验证 P05–P13 工件确定性重建的只读快照。它是实际投影产物，不是
   浏览器硬编码或实时市场声明；所有 fixture、Paper、回测和非生产限制必须随记录传递。
4. FastAPI 固定为 `0.141.1`，Uvicorn 固定为 `0.52.4`。版本由 FastAPI 官方 release notes、
   PyPI 实际索引和本机 Python 3.13 契约核对；OpenAPI 由运行中的应用生成，不手写第二份规范。
5. REST 使用 `/api/v1`，WebSocket 使用 `/ws/v1/stream` 且 schema 独立版本化。WS 只用于非权威
   增量；客户端发现 sequence gap 后必须停止应用事件，通过 REST snapshot 恢复，再从新水位继续。
6. TypeScript 客户端使用 `@hey-api/openapi-ts 0.99.0` 从实际 OpenAPI 生成 SDK、类型与内置
   Fetch 客户端；该版本明确支持 TypeScript 6，生成结果进入差异检查，
   避免维护重复手写 DTO。最初候选 `openapi-typescript 7.13.0` 的 peer contract 仅允许
   TypeScript 5，实际安装门禁拒绝后未继续绕过；已废弃的独立 `@hey-api/client-fetch` 包也未保留。
7. Next.js 保留现有 16.3.3 App Router。Storybook 使用官方支持的 Next.js Webpack 框架
   `10.5.10`；官方首选的 Vite 框架实际安装时经 `tsconfck 3.1.6` 暴露 TypeScript 5-only peer
   contract，与项目锁定的 TypeScript 6.0.3 冲突，因此选择官方仍支持的 Webpack 5 路径并用
   Storybook build 验证。Webpack 固定为已通过最小发布时间门禁的 `5.109.2`，不使用安装器曾建议
   豁免的新发布 `5.110.3`。ECharts 使用 `6.1.0` 并在 Client Component 中延迟初始化，
   Lightweight Charts 使用 `5.2.1` 且仅在 Client Component 初始化。实际版本由 npm registry 与
   官方文档核对；P15 若页面图表规模扩大，再以生产 bundle 证据决定是否切换到按图表注册的 core
   import，P14 不为推测性收益增加额外封装。
8. Storybook 采用一个全组件状态画廊覆盖正常、加载、空、陈旧、降级、断开、错误、窄屏和无障碍
   场景。该做法保留逐组件覆盖，同时避免复制数百份只改一个状态的样板 Story。
9. Web/API 只绑定 loopback；API 没有交易写端点。前端权限固定最小 `VIEWER`，无登录或伪造认证
   能力；成熟 OIDC/Passkey 接入属于后续部署安全阶段。Next.js 使用每请求 nonce CSP，开发环境仅按
   官方要求允许 `unsafe-eval`，图表所需 style attribute 单独限制，不放宽脚本策略。
10. P14 不部署公网，不使用 Sites 托管；本阶段交付物是本地私有工作台。`LIVE_TRADING` 保持锁定，
    不连接真实账户、Testnet 或 Live 网络。

## 官方证据

- FastAPI release notes（0.141.1）：<https://fastapi.tiangolo.com/release-notes/>
- Storybook Next.js with Vite：<https://storybook.js.org/docs/get-started/frameworks/nextjs-vite/>
- Apache ECharts npm/tree-shaking：<https://echarts.apache.org/handbook/en/basics/import/>
- Lightweight Charts 5.x：<https://tradingview.github.io/lightweight-charts/docs/5.0>
- Next.js 16.3.3 本地随包文档：
  `apps/web/node_modules/next/dist/docs/01-app/02-guides/content-security-policy.md`

## 后果

- 看板可在没有数据库常驻进程时读取可审计快照；生产式持久化仍有 PostgreSQL 实契约，二者使用同一
  Read Model schema 和内容哈希。
- API/前端不会因 P14 获得任何订单或账户写权限；未来新增受审计 POST 必须另建 ADR、鉴权、CSRF
  和幂等契约。
- nonce CSP 使页面动态渲染并放弃静态 CDN 优化；本地高敏感工作台优先安全，性能由自动基准约束。
- P14 快照只证明投影、查询和可视化链路，不证明实时市场新鲜度、策略收益或实盘容量。

## 回退条件

若 FastAPI、Next.js、Storybook 或图表库的锁定版本出现安全公告或契约破坏，先用官方稳定版和自动
契约测试验证，再通过新 ADR 更新锁文件；禁止静默漂移或在前端复制服务端口径绕过升级。
