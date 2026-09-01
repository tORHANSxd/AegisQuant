# P09 实施计划

## 目标与边界

P09 在 P02 的不可变数据与来源政策、P06 的统一事件回测、P07 的严格验证和 P08 的
Proposal-only AI 边界之上，建立外部知识与策略情报工程。所有外部内容均视为不可信输入；
Python、Notebook、HTML 和附件只允许归档、清洗、解析与静态分析，未经后续明确许可和隔离
沙箱准备不得导入或执行。

本阶段实现公开索引候选规范化、聚宽及其他平台手工导出包安全导入、Source Manifest/
Artifact/Rights/Evidence Span、Python/Notebook AST 扫描、Strategy IR、偏差审计、七层去重、
传统市场到加密市场迁移和三套从零重写候选的统一事件回测。真实聚宽导出尚未提供时只使用
项目自有合成夹具验证 importer 与分析器，并把真实来源状态记为 `awaiting_user_export`，不得
伪造正文、作者、历史收益或复现结论。

用户推荐的 `HKUDS/AI-Trader` 只作为外部架构线索。因当前仓库根目录未发现明确许可证文件，
其权利状态按 `unknown` 处理：记录来源和观察结果，不复制源码、不执行安装指令、不注册外部
服务、不发送信号，也不把其排行榜或宣传结果当作 AegisQuant 证据。

项目业主要求全部工程完成后统一正式验收。依据 ADR-0010，P09 完成实现和规定测试后保持
`in_progress`，不生成 `ACCEPTANCE.md`，不写 `accepted_at_utc`。始终保持
`LIVE_TRADING=false`、`live_trading_locked=true`；不连接真实交易账户，不请求或保存密码、
Cookie、验证码或 API Secret。

## 实施顺序

1. 固化 P09 需求追踪和外部知识安全、许可、执行隔离 ADR。
2. 实现严格 Source Manifest、Artifact、Rights、Evidence Span、Strategy IR、审计、去重和迁移模型。
3. 实现手工导出目录和 ZIP 的限额、路径穿越、符号链接、文件类型、哈希、不可变发布与 HTML
   安全清洗；Notebook 仅解析代码单元，不执行内核。
4. 实现 Python AST 静态分析，识别导入、网络、文件、子进程、反序列化、动态导入、凭据、删除、
   平台 API、参数、调度、数据查询、交易、调仓、风控和时间/成交风险。
5. 实现规则解析与 AI 候选双通道 Strategy IR；所有结论必须链接证据，缺失参数保持
   `missing/unsupported`，AI 只能提交不可执行 Proposal。
6. 实现未来函数、available-time、幸存者、成交时点、成本、参数选择、尾部风险和规则不一致审计。
7. 实现代码哈希、归一化 AST、Strategy IR、信号、交易/持仓、因子/状态暴露和残差 Alpha 七层去重。
8. 实现传统市场到加密市场的语义迁移记录；从零重写趋势突破、24/7 UTC 状态反转和资金费率/
   基差三套简单候选。
9. 使用 P06 事件引擎、同一规则/成本政策、合成但可复现的市场夹具统一回测三套候选；保留订单、
   成交、账本和经济事件哈希，不宣称盈利或外部策略复现成功。
10. 完成 NautilusTrader、LEAN、Qlib、VeighNa、Hummingbot、Freqtrade/FreqUI、OpenBB、Grafana
    以及用户推荐 AI-Trader 的官方资料评审和采用/拒绝边界。
11. 生成 SOURCE/STRATEGY Parquet 目录、Alpha 原语、重复簇、失败分类、迁移队列、复现记分板、
    静态分析报告和后续资料请求队列。
12. 运行 P09 定向测试、全量 pytest、Ruff、Pyright、Python 3.14 契约、mutation、安全/秘密/
    依赖/许可证扫描、前端测试与构建。
13. 生成延期验收口径的 SUMMARY、TEST_RESULTS、RISKS、NEXT_ACTIONS、ARTIFACT_MANIFEST、
    ADR_REFERENCES，更新阶段状态并执行一次本地 Git 归档。

## 验证标准

- 扫描恶意 Python/Notebook 不产生任何文件、网络、子进程或导入副作用。
- ZIP 路径穿越、符号链接、超限条目、压缩炸弹、宏和不允许类型均失败关闭。
- 导入相同内容得到相同哈希；同一 `source_id` 的不同内容不能覆盖既有归档。
- 每条 Strategy IR 规则都能回到精确文件/行证据；AI 不能补造缺失参数或执行来源代码。
- 复制、改名和语法等价策略在 AST/IR 层进入同一重复簇；多层指纹分别保留，不能把名称当 Alpha。
- 三套迁移候选使用同一事件引擎、成本、规则和数据契约，输出订单、成交、账本及可复现命令。
- 权利未知或受限内容只能生成内部元数据，不进入公开正文工件。
- `LIVE_TRADING` 保持锁定，外部框架和 AI-Trader 均未执行、未认证、未连接账户。

## 明确非目标

- 不绕过聚宽登录、地区限制、验证码或隐藏接口，不保存账号密码、Cookie 或验证码。
- 不实现后台批量抓取；本阶段不制作浏览器扩展，因为 importer 已覆盖手工导出且扩展为可选任务。
- 不接入真实 JQData、云 LLM、交易账户、Testnet 或任何下单端点。
- 不执行外部源码、Notebook、宏、安装脚本或仓库提供的 Agent Skill。
- 不把合成夹具、来源回测、GitHub Star、排行榜或宣传收益当作策略有效性证据。
- 不开始 P10，不生成正式 `ACCEPTANCE.md`。
