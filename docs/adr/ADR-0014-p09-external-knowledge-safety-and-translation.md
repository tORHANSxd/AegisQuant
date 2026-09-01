# ADR-0014：P09 外部知识安全、许可与迁移政策

- 状态：Accepted by project owner through autonomous P09 execution authorization
- 日期：2026-09-02

## 背景

P09 需要处理聚宽手工导出、社区文章、Python、Notebook、HTML、附件和外部框架资料。这些输入
可能包含恶意代码、宏、反序列化载荷、路径穿越、压缩炸弹、提示词注入、未来函数、虚假收益和
不明确许可。用户推荐 `HKUDS/AI-Trader` 供量化内容借鉴；其当前公开仓库的产品方向已转为
Agent 信号市场、复制交易和外部注册，且根目录未观察到明确许可证文件，不能把“公开可见”等同
于“可复制、可执行或适合本项目安全边界”。

## 决定

1. 外部代码采用单向门禁：`UNSCANNED → QUARANTINED → STATIC_ANALYZED → REVIEW_REQUIRED`。
   P09 不提供把来源代码推进到可执行状态的 API；分析器只读取字节、JSON 和 Python AST。
2. 手工导出 importer 只接受严格 manifest 和允许类型，限制单文件、总大小、文件数和压缩比；
   拒绝绝对路径、父目录穿越、符号链接、设备文件、宏和未知可执行格式。发布采用内容寻址的
   不可变目录，同一 Source ID 的不同内容视为冲突，绝不覆盖。
3. 原始 HTML 与清洗文本分离。清洗器删除 script/style/iframe/object/embed、事件处理属性和
   活跃 URL；Notebook 只读取 code cell 文本，永不启动 kernel；Python 永不 import。
4. Strategy IR 只能包含由规则解析器或结构化 AI Proposal 给出的候选。每个非缺失规则必须引用
   文件、行号和内容哈希 Evidence Span；AI 候选引用不存在证据、补造参数或请求发布/执行时失败。
5. Rights 状态分为 `public_license`、`personal_research_only`、`unknown`、`prohibited`。只有明确
   `public_license` 的内容可进入公开正文工件；其余只保留合规范围内的内部元数据、哈希、短证据
   定位和访问状态。未知许可绝不因 GitHub、搜索索引或用户可访问而自动升级。
6. 七层去重分别保留文本/代码、归一化 AST、Strategy IR、信号相关、交易/持仓重叠、因子/状态
   暴露和残差 Alpha 证据。名称、作者和来源收益不参与“独立 Alpha 数量”的乐观计数。
7. 传统市场迁移是从零经济语义重写，不复用来源成交函数。P09 首批候选为趋势突破、24/7 UTC
   状态反转和资金费率/基差；统一使用 P06 事件引擎、历史规则、成本、成交和账本输出。合成夹具
   只证明实现和复现契约，不证明可盈利。
8. 框架评审只采用官方稳定文档和公开契约。NautilusTrader 保留为事件引擎参考；LEAN/Qlib/
   VeighNa/Hummingbot/Freqtrade 只吸收模块边界和审计启发；OpenBB 用作可组合研究工作区参考；
   Grafana 仅用于运维可观测性。P09 不安装或执行这些新框架。
9. AI-Trader 只记录 README/OpenAPI 暴露的架构线索。其自动注册、信号发布、复制交易、外部生产
   API 和任何 Agent Skill 均不调用；不复制代码。可借鉴的只有“API 契约显式化”和“前台服务与
   后台任务隔离”等一般工程思想，且须由 AegisQuant 自己实现和测试。
10. 真实聚宽资料未提供时，真实来源目录保持 `awaiting_user_export`。不请求密码、Cookie、验证码；
    不以合成夹具伪称真实导入或复现。浏览器扩展是可选项，本阶段以更小攻击面的手工导出 importer
    完成任务，不创建无必要扩展。
11. `LIVE_TRADING=false`、`live_trading_locked=true`。P09 无账户、执行适配器、真实订单或秘密
    能力；正式验收继续按 ADR-0010 延期。

## 后果

- 来源代码不能“顺手跑一下”，分析和重写成本更高，但恶意代码、许可和未来函数不会混进研究基线。
- 权利未知的高热度仓库可能只得到元数据结论；这比拿 Star 当许可证靠谱，少整点赛博玄学。
- 三套迁移候选可能全部表现一般或亏损，结果仍完整保留；P09 的成功标准是可审计、可复现和安全，
  不是凑一条漂亮曲线。

## 外部契约依据

- NautilusTrader 文档：<https://nautilustrader.io/docs/>
- QuantConnect LEAN Algorithm Framework：<https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/overview>
- Qlib Portfolio Strategy：<https://qlib.readthedocs.io/en/latest/component/strategy.html>
- VeighNa 用户文档：<https://www.vnpy.com/docs/cn/index.html>
- Hummingbot Strategy V2：<https://hummingbot.org/strategies/v2-strategies/>
- Freqtrade Backtesting：<https://docs.freqtrade.io/en/stable/backtesting/>
- OpenBB Workspace：<https://docs.openbb.co/workspace>
- Grafana Provisioning：<https://grafana.com/docs/grafana/latest/administration/provisioning/>
- HKUDS/AI-Trader：<https://github.com/HKUDS/AI-Trader>
