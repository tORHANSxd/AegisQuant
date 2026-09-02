# P15 ADR 引用

- `ADR-0020`：P15 完整工作台、扩展 Read Model、只读 API、七段订单追溯、下采样、缓存、浏览器、
  可访问性、历史 P14 契约冻结及锁定 Node/pnpm 启动路径的直接决策。
- `ADR-0019`：P14 PostgreSQL Read Model、只读 REST/WebSocket、生成客户端、CSP 和 Storybook 基线。
- `ADR-0018`：P13 Paper/Shadow/事故与运行证据作为 P15 只读投影输入的语义来源。
- `ADR-0010`：正式验收统一后置，阶段实现完成不等于验收通过。
- `ADR-0003`：`LIVE_TRADING` 默认拒绝与不可旁路锁定。
- `ADR-0001`：Python、Node、pnpm 与依赖版本政策。

P15 以 Next.js 16.3.3 随包官方文档、运行时 FastAPI OpenAPI、实际生成客户端和三浏览器构建测试为
契约依据。收口时发现主机 pnpm 启动器实际使用 Node 24.12.0，与锁定的 24.20.0 不一致；没有降低
engine 约束或隐瞒警告，而是在 ADR-0020 固化“直接调用仓库内 Node/pnpm、缺失即失败”的决策，并以
最终 46/46 CI 和零 `v24.12.0` 命中验证。P14 的历史 OpenAPI/WS 证据不再由 P15 扩展运行时反向覆盖，
当前漂移由 P15 合约生成器负责。
