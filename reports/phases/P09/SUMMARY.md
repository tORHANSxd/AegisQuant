# P09 实施总结

P09 已完成外部知识与策略情报工程实现；正式验收按项目业主决定延期。阶段保持
`in_progress`，不生成 `ACCEPTANCE.md`，不写入 `accepted_at_utc`。P10 尚未启动。

## 已交付

- 严格的 Source Manifest、Source Artifact、Rights、Evidence Span、Strategy IR、审计、去重和
  传统市场到加密市场迁移模型。
- 只接受用户合法手工导出目录或 ZIP 的不可变 importer：限制路径、符号链接、文件类型、数量、
  大小和压缩比；原始文件按哈希归档，HTML 另产出惰性纯文本，Python/Notebook 永不执行。
- Python/Notebook AST 静态分析：识别网络、文件写入、子进程、危险反序列化、动态执行、凭据、
  删除、平台 API、调度、数据查询、交易、风控、墙钟、负向 shift 和末行索引语义。
- 规则 AST 与 AI Proposal 双通道 Strategy IR；所有受支持规则精确链接 Evidence Span，缺失信息
  保持 `missing/unsupported`，AI 不能补造证据、发布或执行。
- 文本/代码哈希、归一化 AST、Strategy IR、信号、交易/持仓、因子/状态暴露和残差 Alpha 七层
  去重；复制改名策略合并为一个独立 Alpha 计数。
- 趋势突破、UTC 时段反转、资金费率/基差三套从零重写候选，统一使用 P06 事件引擎、历史规则、
  成本、成交和账本契约运行合成回放；结果不构成 Alpha 或盈利声明。
- NautilusTrader、LEAN、Qlib、VeighNa、Hummingbot、Freqtrade/FreqUI、OpenBB、Grafana 与
  HKUDS/AI-Trader 的契约评审，以及 Source/Strategy Parquet 目录、原语、重复簇、失败分类、
  迁移队列、复现记分板和后续资料请求队列。

## 外部资料边界

真实聚宽导出尚未提供，状态为 `awaiting_user_export`；当前 importer 与分析证据只使用项目自有
合成夹具，未伪称真实来源或复现。AI-Trader 固定观察 revision
`d03ff6c056b32ced735adf7c19ed8175adb1c8df`，因未观察到根许可证文件而按 `unknown` 处理；未复制
或执行其代码，未调用 Agent Skill、注册、信号发布、复制交易或生产 API。

## 验证结果

- 完整 CI：31/31 阶段通过；Python 3.13.15 全量测试 386/386 通过。
- Python 3.14.7 隔离候选契约：349/349 通过；Ruff 与 Pyright 均为 0 问题。
- P09 关键变异：8/8 被杀死，得分 1.0，高于 0.90 门槛。
- Secret 命中 0；Python/JavaScript 依赖审计、Bandit、SBOM 与许可证清单通过，Python 未知
  许可证计数为 0。
- 前端 lint、类型检查、单测、生产构建与 Playwright E2E 全部通过。
- Python 3.14 首次预跑发生 2 个顺序性失败，原因是最终 P09 报告尚未生成；补齐真实报告后完整
  重跑 349/349 通过。该失败保留在 `TEST_RESULTS.json`，没有把预跑当成功。

## 安全与状态

`LIVE_TRADING=false` 且 `live_trading_locked=true`。未连接真实交易账户、未认证、未下单，未索取
或写入密码、Cookie、验证码或 API Secret。浏览器扩展是可选项；手工 importer 已覆盖需求且攻击
面更小，因此 P09 未创建扩展。实现提交为
`cec93910507d4410e9547071621105377e3de0dd`；最终测试与清单见 `TEST_RESULTS.json` 和
`ARTIFACT_MANIFEST.json`。
