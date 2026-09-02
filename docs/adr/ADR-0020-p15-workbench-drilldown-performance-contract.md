# ADR-0020：P15 完整工作台、跨域下钻与浏览器性能契约

- 状态：Accepted
- 日期：2026-09-02
- 阶段：P15

## 背景

P15 必须实现第 17 章的完整页面、全局交互、K 线回放和跨模块决策链，同时保持 P14 的只读、
loopback、来源哈希和 Live lock 边界。现有 12 类基础投影不足以表达成交、市场回放、研究运行、
事故、系统状态、对账和逐订单追溯；若直接在浏览器读取报告或拼造指标，会破坏服务端口径与可审计性。

## 决定

1. 扩展现有不可变 Read Model，而不是建立第二套网页专用数据源。新增投影必须继续使用严格 Pydantic
   payload、十进制字符串、`as_of_time`、来源文件 SHA-256、质量状态和内容哈希；数据只来自已验证的
   P04–P14 工件与公开历史夹具。缺失的实时、容量或生产字段明确标为不可用，禁止补造。
2. 新增成交、执行质量、信号、市场状态、研究运行、模型监控、事故、系统健康、对账及订单追溯投影。
   每个展示订单都有固定顺序的 Signal→Event Evidence→Model→Risk→Order→Fill→Ledger 链；不适用的
   阶段使用 `NOT_APPLICABLE` 并给出可核验原因，缺证据则使用 `NOT_AVAILABLE`，不得伪造关联。
3. API 继续只提供 GET。P15 不实现告警确认或研究取消写接口，因为它们在缺少 P16 身份、CSRF、审计与
   幂等保障时会扩大攻击面；设置仅存于浏览器本地且只含显示、时区、筛选和布局偏好。
4. 长时序采用确定性的服务器端 min/max bucket 下采样，保留首点、末点和桶内极值；表格使用游标分页
   和浏览器窗口渲染。快照响应使用内容哈希 ETag 与私有重验证缓存，health 和错误仍 `no-store`。
5. Next.js 保持已锁定的 16.3.3 App Router。按随包官方文档，数据读取保留在 Server Components，
   仅全局筛选、命令面板、导出、布局、图表和偏好进入窄 Client Component 边界；根级边界与重点路由
   提供 `loading.tsx`、`error.tsx`，页面错误不得影响独立运行的 Read API。
6. 页面使用共享工作台框架和领域配置来减少重复，但每个路由必须有领域专属指标、解释、表格或图表，
   不能以“稍后实现”卡片冒充完成。Overview、PnL、风险、数据和对账状态保持首屏可见。
7. 中文是默认语言；所有 PnL 指标展示公式、口径、来源和截至时间。颜色只作冗余编码，状态文本、图表
   数据表、焦点样式、跳转链接、键盘命令和窄屏导航必须满足 WCAG 2.2 AA 可验证路径。
8. 浏览器验证覆盖 Chromium、Firefox、WebKit 配置与 390px 窄屏；产品视觉回归以 Chromium 固定基线
   执行。Overview p75 预算 1.5 秒，API 快照 p95 预算 300ms，大表逻辑 100,000 行只渲染固定窗口。
9. 本阶段仍是历史开发/Paper/fixture 工作台，不连接真实账户或交易所，不开放订单、风险上限、模型发布、
   凭据或 Live 解锁入口。`LIVE_TRADING` 始终锁定。
10. P15 有意扩展 P14 的 OpenAPI、WebSocket topic 和共享 TypeScript 客户端。P14 历史契约与证据作为冻结
    工件由 P14 阶段测试和清单校验，不再用扩展后的运行时重新生成；当前运行时漂移由 P15 合约生成器负责。
11. 本地完整 CI 直接调用仓库忽略目录中的 Node 24.20.0 可执行文件和 pnpm 11.24.0 入口；任一文件缺失即
    拒绝运行，不再通过主机 PATH 解析 pnpm，避免系统 Node 24.12.0 悄悄承载前端门禁。

## 实际契约依据

- Next.js 16.3.3 随包文档：`apps/web/node_modules/next/dist/docs/01-app/01-getting-started/`
  下的 layouts/pages、server/client、fetching-data 和 error-handling 文档。
- 项目锁文件与实际构建：Node 24.20.0、pnpm 11.24.0、React 19.2.8、TypeScript 6.0.3、
  Playwright 1.62.1、ECharts 6.1.0、Lightweight Charts 5.2.1。
- OpenAPI 和 TypeScript 客户端继续由运行时 FastAPI 契约生成并执行差异检查，不手写重复 DTO。

## 后果

- 13 个新增业务路由和既有 Overview/Intelligence 共享同一来源可信链，页面复用不会牺牲领域语义。
- 明确的 `NOT_APPLICABLE`/`NOT_AVAILABLE` 可能比“全绿链路”难看，但它准确揭示研究基线没有消费模型
  或事件的事实，避免把松散工件误说成因果关系。
- P15 不提供事故确认等写操作；这些能力推迟到 P16 安全边界完成后再评估。

## 回退条件

若新增投影无法从来源工件确定性重建、下采样破坏首末/极值、页面必须依赖交易写权限，或主流浏览器
契约测试失败，则回退相关页面到明确的只读不可用状态并阻断 P15 实现完成，禁止放宽 Live lock。
