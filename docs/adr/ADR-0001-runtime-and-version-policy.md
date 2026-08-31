# ADR-0001：运行时与版本策略

- 状态：Accepted
- 日期：2026-08-31
- 范围：P00

## 背景

任务书给出 Python 3.13 正式线、3.14 候选线、Node LTS、Next.js、React 和
NautilusTrader 的参考版本，并要求 P00 重新读取官方稳定版本，以实际契约优先。

## 决定

生产基线锁定 Python 3.13.15、Node.js 24.20.0、pnpm 11.24.0、Next.js 16.3.3、
React 19.2.8 和 NautilusTrader 1.231.0。Python 3.14.7 只运行兼容性候选契约，不是
生产运行时。所有直接依赖使用精确版本，`uv.lock` 与 `pnpm-lock.yaml` 为解析事实。

版本解析时，npm 最新版 ESLint 10.9.1 与 Next.js 传递的
`eslint-plugin-import/react/jsx-a11y` peer 范围冲突；TypeScript 7.0.2 也超出
`typescript-eslint` 的 `<6.1.0` 范围。严格 peer 安装实际失败，因此锁定仍在受支持
范围内的 ESLint 9.39.5 与 TypeScript 6.0.3。禁止通过关闭严格 peer 检查掩盖冲突。

pnpm 11 默认拒绝未批准的依赖构建脚本。Next.js ESLint 解析链需要
`unrs-resolver@1.12.2` 的 `napi-postinstall` 来选择已锁定的平台二进制；检查其 3 行
postinstall 入口后，通过 pnpm 11 的 `allowBuilds` 只允许精确版本
`unrs-resolver@1.12.2` 执行构建脚本，其余依赖继续默认拒绝。任务书参考的旧
`onlyBuiltDependencies` 已被 pnpm 11 移除，故以官方现行配置契约为准。

Next.js 16 会由 `next dev`、`next build` 和 `next typegen` 重写 `next-env.d.ts`。开发
和生产生成目录同时存在时，Next 16.3.3 自动扩展的 `tsconfig` 会重复载入两套全局
路由类型。当前官方文档描述了 `experimental.isolatedDevBuild` 开关，但锁定版本的实际
`NextConfig` 类型和运行时代码均不接受该字段，因此不照抄不兼容配置。类型门禁采用
官方建议的 `next typegen`，随后由 `tsconfig.check.json` 明确只检查生产 `.next/types`；
生产 build 也通过官方 `typescript.tsconfigPath` 使用同一检查配置。Next 管理的
`tsconfig.json` 仍保留开发类型供 IDE 使用。`next-env.d.ts` 作为生成物忽略，不进入
版本库。该处理已用 build/E2E/typecheck 交错执行的契约验证。

NautilusTrader 1.231.0 的上游成熟度元数据仍为 Beta；因此 P00 只验证确定性回放，
不得由此推导任何实盘可用性。Windows 客户端兼容性以本机导入和回放契约为准。

`uv 0.12.7` 在本机并行安装两个解释器后创建次版本 junction 时返回 exit 2，但精确
目录中的 `python.exe` 分别报告 3.13.15 和 3.14.7，且 3.13.15 完成锁解析与环境同步。
因此后续命令使用精确解释器路径，并由完整契约决定可用性；不把安装命令的异常返回
码涂成成功。

## 证据与后果

版本来源、宿主实际值和契约结果写入 `state/DEPENDENCY_MATRIX.json` 与 P00
`TEST_RESULTS.json`。任何锁定版本无法解析或契约失败都会阻断 P00 验收，而不是静默
改用别的版本。
