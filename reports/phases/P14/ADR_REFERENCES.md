# P14 ADR 引用

- `ADR-0019`：P14 Read Model、PostgreSQL、只读 REST/WebSocket、生成客户端、Storybook、图表、
  CSP 与依赖安全处置的直接决策。
- `ADR-0018`：P13 Paper/Shadow/事故和运行证据作为只读投影输入的语义来源。
- `ADR-0010`：正式验收统一后置，阶段实现完成不等于验收通过。
- `ADR-0004`：沿用 PostgreSQL、SQLAlchemy、Psycopg 和迁移边界。
- `ADR-0003`：`LIVE_TRADING` 默认拒绝与不可旁路锁定。
- `ADR-0001`：Python、Node、pnpm 与依赖版本政策。

实际依赖契约曾与初始候选不一致：TypeScript 6 拒绝 TypeScript 5-only 的 Vite 依赖链；
`@storybook/nextjs 10.5.10` 又引入无可用修复版的 `image-size 2.0.2`。最终采用官方
`@storybook/react-webpack5 10.5.10`、官方推荐 SWC compiler addon 4.0.3，并将 `js-yaml`
override 到 4.3.2。选择依据、官方链接、供应链扫描和实际构建结果均固化在 ADR-0019；没有通过
忽略审计、放宽 peer contract 或伪造兼容性来过门禁。
