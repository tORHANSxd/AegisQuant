# AegisQuant v3.1：个人 AI 加密资产多模态市场情报、预测、交易与可视化系统——Codex 从零实施总任务书

> **文档性质：** 单一事实来源（Single Source of Truth）与最高优先级工程规格  
> **实施起点：** 空目录，从零开始  
> **规格日期：** 2026-08-31  
> **默认语言：** 中文界面与中文文档；代码、标识符和协议字段使用英文  
> **默认时区：** 内部一律 UTC；用户展示默认 Asia/Tokyo，可配置  
> **目标用户：** 单一所有者、个人研究与自营交易  
> **首要交易场所：** Binance；后续接入 OKX、Bybit、Deribit  
> **安全默认值：** `LIVE_TRADING=false`，不允许从网页直接任意下单  
> **核心升级：** 市场行情、订单流、链上、宏观、全球时事、新闻、公告、X 推文及其他获授权社交信息进入同一 point-in-time 事件智能体系；任何单一消息都不能直接控制交易。  
> **版本：** 3.1.0  

---

## v3.1 相对 v3.0 的强制变更

本版本不是可选补丁。Codex 必须把以下内容视为核心架构：

1. 将全球新闻、监管、官方公告、X 推文和获授权社交/频道信息提升为第一等数据源。
2. 新增来源许可策略、内容修订/删除、社交互动时点快照和事件知识图谱。
3. 新增 AI 证据委员会、Skeptic Agent、跨源冲突、操纵风险和多时间尺度事件影响预测。
4. 新增 Market-only / Event-only / Fused / Risk-only 四种基线与消融。
5. 新增 `/intelligence` 看板、Event Radar、Evidence Graph、Narrative Monitor 和 Event Replay。
6. X/Telegram/Bluesky 等首批接入提前到 P04；P10 完成生产级多源融合。
7. 单一新闻或推文不得直接下单；事件只能先形成带证据的预测或签名风险事件，再经过组合和独立风险引擎。

# 0. 给 Codex 的最高优先级执行契约

本文件替代此前所有 AegisQuant、聚宽情报工程和网页版看板的旧计划、补丁与阶段状态。项目目录已经清空，**不得假定任何旧代码、JQ-0 产物、数据库、配置、模型或阶段报告仍然存在**。如果在外部目录发现旧资产，只能把它们作为待审计的只读输入，不能把它们当作已验收模块。

### 0.1 规范词义

本文中的规范词义如下：

- **必须**：不满足即验收失败。
- **禁止**：出现即停止阶段并生成事故报告。
- **应当**：除非有书面 ADR 说明，否则必须执行。
- **可以**：可选实现，不得成为后续阶段的隐式前提。
- **候选**：必须经过基准、消融、样本外和成本测试后才能晋升。

### 0.2 执行方式

Codex 必须遵循以下流程：

1. 完整读取本文件，先生成规格索引和需求可追踪矩阵。
2. 从 `P00` 开始；一次只实施一个阶段。
3. 每个阶段先写实施计划，再编写代码，再运行测试，再生成验收材料。
4. 当前阶段未通过时，不得进入下一阶段。
5. 不得以“后续补齐”为理由提交占位函数、空实现、伪造数据或跳过测试。
6. 发现规格冲突时，选择更安全、更可复现、更容易审计的解释，并记录 ADR。
7. 发现依赖版本、API 或交易所规则已经变化时，以官方文档和自动契约测试为准，不得依赖记忆硬编码。
8. 不得一次性尝试完成全部项目。第一轮只执行 `P00`。

### 0.3 每个阶段的强制产物

每个阶段 `Pxx` 必须生成：

```text
reports/phases/Pxx/
├── PLAN.md
├── SUMMARY.md
├── TEST_RESULTS.json
├── ACCEPTANCE.md
├── RISKS.md
├── NEXT_ACTIONS.md
├── ARTIFACT_MANIFEST.json
└── ADR_REFERENCES.md
```

全局状态必须保存在：

```text
state/PROJECT_PHASE_STATE.yaml
state/REQUIREMENTS_TRACEABILITY.csv
state/OPEN_RISKS.yaml
state/DEPENDENCY_MATRIX.json
state/DATA_ACCESS_STATUS.yaml
```

`PROJECT_PHASE_STATE.yaml` 至少包含：

```yaml
spec_version: "3.1.0"
current_phase: "P00"
status: "not_started"   # not_started | in_progress | blocked | failed | accepted
started_at_utc: null
accepted_at_utc: null
commit_sha: null
artifact_manifest_sha256: null
live_trading_locked: true
next_phase: "P01"
```

### 0.4 代码质量硬要求

必须满足：

- Python 严格类型检查；前端 TypeScript `strict=true`。
- 所有公共接口有类型、错误语义和示例。
- 核心领域逻辑不得依赖全局可变状态。
- 时间、金额、数量、价格和精度规则必须集中管理。
- 交易、风险、账本和对账路径不得使用浮点数表示权威金额。
- 数据、模型、策略、配置和回测都必须可追溯到内容哈希。
- 所有随机过程固定并记录种子。
- 单元、属性、契约、集成、回放和端到端测试分层存在。
- 外部 API 必须有超时、重试上限、限频、熔断和幂等策略。
- 外部新闻/社交内容必须有来源政策、修订/删除同步、证据引用和提示词注入隔离。
- 禁止在日志、异常、网页、测试快照或 Git 中泄露密钥。
- 禁止将 Notebook 作为唯一生产实现。
- 禁止以收益截图代替原始成交、净值序列和实验清单。

### 0.5 安全与交易权限硬边界

以下规则没有例外：

1. AI、LLM、研究代理和网页前端永远不能持有实盘 API 私钥。
2. 研究代码不能直接调用实盘下单适配器。
3. 首版网页只能读取交易状态；只允许受审计的低风险控制，如暂停研究任务、确认告警。
4. 任意实盘权限必须经过独立的、可过期的人工解锁流程。
5. 实盘密钥必须禁用提现权限，并尽可能启用 IP 白名单和子账户隔离。
6. 未完成回放、Paper、Shadow、Testnet 和 Canary 验收前，`LIVE_TRADING` 必须保持锁定。
7. 不得绕过交易所地域、账户、合规、速率、付费或访问权限限制。
8. 不得自动破解验证码、模拟未授权登录、上传用户 Cookie、逆向隐藏接口或抓取无权访问的社区内容。
9. 不得读取私信、受保护账号、未授权群组，或使用 self-bot/共享 Token 获取社交内容。
10. 所有外部源码在静态分析和沙箱批准前禁止执行。
11. 任何不确定订单状态都必须先查询和对账，不得盲目重发。
12. 任何新闻、推文或 LLM 判断都不能绕过组合、风险和实盘锁。

### 0.6 失败处理

出现以下任一情况，Codex 必须停止当前阶段并标记 `failed` 或 `blocked`：

- 测试不稳定或重复运行结果不同且无法解释；
- 数据存在未来泄漏、时间戳语义不明或无法建立 point-in-time 视图；
- 账本与交易所余额无法对账；
- 风险引擎可被策略或 AI 绕过；
- 实盘路径意外启用；
- 依赖预发布版本才能满足核心路径；
- 许可证或访问权不允许计划用途；
- 秘密进入版本库或日志；
- 回测结果无法由锁定的数据、配置、代码和种子复现。

---

# 1. 项目使命、成功标准与边界

## 1.1 项目使命

建立一套个人可拥有、可审计、可扩展的加密资产量化平台，使其能够：

```text
市场行情 / 订单流 / 衍生品 / 链上 / 宏观数据
+ 全球时事 / 监管 / 新闻 / 官方公告
+ X 推文 / Telegram 频道 / Bluesky / YouTube / GitHub 等获授权公开信息
→ point-in-time 数据湖、内容谱系与事件知识图谱
→ AI 多代理证据联合判断、冲突核验与不确定性估计
→ 多模态市场状态与多时间尺度影响预测
→ 多策略 Alpha 组合与事件风险覆盖层
→ 成本、容量和风险约束下的组合构建
→ 事件驱动交易执行与完整对账
→ 历史、当日、实时交易和事件情报的优雅网页版看板
→ 持续监控、漂移检测、事故响应和安全停机
```

“预测市场”在本项目中定义为：对不同时间尺度上的收益、波动率、尾部风险、流动性、资金费率、基差、成交概率与成本给出**校准后的条件概率分布**，并允许模型明确选择“不交易”。项目不承诺确定预测价格，也不承诺盈利。

## 1.2 最终系统能力

完成全部必需阶段后，系统应当具备：

- 对现货、永续、交割合约和后续期权的统一市场抽象；
- 对全球新闻、官方公告、X 推文、获授权频道、开发活动和治理事件的统一内容与事件抽象；
- 分钟至日频方向、波动率、尾部和执行预测；
- 针对事件的 `5m/30m/4h/1d/7d` 方向、波动、流动性、基差和尾部影响预测；
- 传统统计、树模型、深度时序模型和时序基础模型的公平竞赛；
- 趋势、横截面、Carry、基差、均值回归、事件和防御策略袖套；
- 严格的样本外验证、过拟合检验、费用与压力测试；
- 双重记账、权威 PnL、仓位、保证金和交易所对账；
- 订单状态机、幂等、部分成交、多腿裸露管理和故障恢复；
- 独立风险引擎与自动熔断；
- 研究、数据、模型、策略、交易、新闻证据、社交传播和事故的全链路谱系；
- 可查看当日与历史量化信息、事件雷达、叙事扩散和证据图谱的专业 Web 看板；
- 本地单机研究与隔离 Linux 实盘部署能力；
- 对外部知识、聚宽资料、论文和开源代码的合规情报工程。

## 1.3 成功标准

系统成功不以某一次最高收益率定义，而以以下标准共同定义：

1. **正确性**：账本、订单、仓位、PnL、风险和时间语义可证明正确。
2. **可复现性**：同一数据版本、代码、配置和种子得到同一结果。
3. **反过拟合**：完整记录所有试验，严格使用样本外、PBO、DSR 和成本压力。
4. **可靠性**：断线、超时、部分成交、重复消息和进程重启不会制造未知仓位。
5. **安全性**：AI 和网页不能越过风险层或取得实盘密钥。
6. **可解释性**：每笔决策能追溯到数据、特征、模型、信号、风险审查、订单、成交和账本分录。
7. **可扩展性**：新增交易所、数据源、模型和策略无需修改核心领域语义。
8. **可运营性**：用户可在一个设计成熟的界面查看系统健康、风险、研究和交易。
9. **经济有效性**：候选策略只有在真实成本、容量和样本外条件下具有增量价值时才晋升。

## 1.4 明确不做

首个生产版本不做：

- 共址、纳秒级 HFT、抢跑或依赖专线优势的策略；
- 无约束强化学习直接控制资金；
- 使用 LLM 自由文本直接下单；
- 浏览器内保存交易所密钥；
- 网页中的任意手工买卖面板；
- 自动破解平台登录、验证码、订阅或付费墙；
- 在没有官方授权的情况下复制、再发布社区受版权保护内容；
- 一开始引入 Kubernetes、Kafka、ClickHouse 集群或大量微服务；
- 因为某个基础模型流行就跳过简单基线；
- 因为回测漂亮就直接实盘；
- 将第三方数据聚合值当作交易所权威账户或成交状态。

## 1.5 已知用户环境与可调整假设

当前已知或默认假设：

```text
CPU: Intel i5-13600KF
GPU: NVIDIA RTX 4070 Ti
RAM: 64 GB
OS: Windows 10/11，可使用 WSL2 和 Docker Desktop
本地资产: 约 100 GB 原始数据 + 约 100 GB 回测/实验结果，路径待提供
首选交易账户: Binance 个人普通 API
可选旧基准: R331，仅在用户提供后作为不可修改的外部基准
```

这些信息不是代码常量。`P00` 必须执行硬件和环境探测，并将结果写入 `state/HOST_CAPABILITIES.json`。路径、额度、账号地区和数据订阅都由访问请求机制收集，不得猜测。

---

# 2. 总体架构与不可破坏的系统原则

## 2.1 六个逻辑平面

系统分为六个逻辑平面，权限单向收紧：

1. **数据平面**：采集、校验、版本化、存储、回放。
2. **事件情报平面**：新闻、公告、社交内容、实体、主张、事件聚类、传播、可信度和影响预测。
3. **研究平面**：特征、标签、实验、模型、策略发现。
4. **决策平面**：行情预测、事件影响预测、信号、组合和风险提案。
5. **交易平面**：风险批准、订单、成交、账本、对账。
6. **运营平面**：Read Model、Web 看板、告警、审计和配置发布。

事件情报平面处理的全部外部文本、图片、音频、视频和链接都属于不可信输入；它只能产出带证据、时间语义、许可状态和不确定性的结构化工件。研究平面只能输出不可变候选，不能直接触达交易平面。决策平面必须通过独立风险引擎。运营平面默认只读。

## 2.2 推荐部署形态：模块化单体优先

首版采用**模块化单体 + 明确进程边界**，避免过早微服务化：

```text
研究工作站
├── 市场与外部内容采集进程
├── Event Intelligence Worker
├── 研究/训练 Worker
├── 回测与回放 Worker
├── API / Read Model
└── Web 前端

隔离交易主机
├── 市场数据与账户流
├── Signal Consumer
├── Risk Engine
├── Execution Engine
├── Ledger / Reconciler
└── Observability Agent
```

Python 包共享统一领域模型，但交易进程、研究进程和网页 API 必须在操作系统权限、密钥和网络层面隔离。只有在监控数据证明单体边界不足时，才允许引入消息代理或拆分更多服务。

## 2.3 权威来源矩阵

| 领域 | 权威来源 | 非权威用途 |
|---|---|---|
| 历史原始市场数据 | 不可变 Parquet + 清单哈希 | 数据库缓存、下采样视图 |
| 交易所合约规则 | 官方 API 的时点快照 | 第三方聚合、人工文档 |
| 账户余额与订单事实 | 交易所账户流 + REST 对账 | 本地预测、缓存 |
| 内部权威 PnL | 双重记账账本 | 前端临时计算、模型估计 |
| 策略定义 | 版本化 Strategy Spec | Notebook 描述 |
| 模型工件 | Model Registry + 内容哈希 | 本地未登记文件 |
| 风险策略 | 签名版本化配置 | 前端输入、LLM建议 |
| 新闻事实 | 原始来源、官方页面、修订快照和证据链 | 聚合标题、LLM 摘要 |
| 社交内容事实 | 官方 API 返回、内容 ID、时间快照和删除同步 | 截图、二手转述、当前互动数 |
| 事件判断 | Claim/Event Graph + 多源证据 + 模型版本 | 单一推文、单一情绪分数 |
| 页面指标 | 服务端 Read Model | 浏览器重算 |
| 事件历史 | 追加式事件日志/Outbox | 控制台文本日志 |

## 2.4 核心事件链

标准决策、事件情报和交易链：

```text
RawExternalContent / SocialPostSnapshot / OfficialAnnouncement
→ NormalizedContent
→ ClaimRecord
→ EventCluster / NarrativeState
→ EventImpactForecast
                         ↘
MarketEvent → FeatureSnapshot → ContextSnapshot
                         ↗
→ ForecastBundle
→ AlphaSignal
→ PortfolioProposal
→ RiskDecision
→ ApprovedOrderIntent
→ OrderCommand
→ VenueOrderUpdate
→ FillEvent
→ LedgerEntries
→ PositionSnapshot
→ ReadModelProjection
→ Dashboard / Alert
```

`ContextSnapshot` 必须同时描述市场微观结构、衍生品、链上、宏观、已确认事件、未确认传闻和数据质量。任何 LLM 摘要都不能替代原始证据对象。

每个对象必须包含：

- 全局唯一 ID；
- `event_time`、`available_time`、`ingest_time`；
- 生产者和版本；
- 上游对象引用；
- 配置、数据和代码哈希；
- 幂等键；
- 可序列化版本号。

## 2.5 数据流和控制流边界

禁止出现：

```text
Notebook → 实盘交易所
LLM → Risk bypass
Dashboard → 任意订单
第三方聚合数据 → 账户权威状态
单一新闻/推文 → 直接下单
外部文本 → 工具调用或系统指令
当前点赞/转发数 → 历史时点特征
前端 JavaScript → 权威 PnL
回测配置 → 自动发布实盘
未验收模型文件 → Signal Service
```

允许的发布路径：

```text
研究工件
→ 验证报告
→ Model/Strategy Registry 候选
→ 人工批准
→ Shadow/Paper 配置
→ Testnet
→ Canary 发布包
→ 独立实盘解锁
```

## 2.6 运行模式状态机

系统至少支持：

```text
OFFLINE_RESEARCH
HISTORICAL_REPLAY
BACKTEST_VECTOR
BACKTEST_EVENT
PAPER
SHADOW
TESTNET
CANARY_LIVE
LIMITED_LIVE
HALTED
```

合法迁移：

```text
OFFLINE_RESEARCH
  → HISTORICAL_REPLAY / BACKTEST_*
  → PAPER
  → SHADOW
  → TESTNET
  → CANARY_LIVE
  → LIMITED_LIVE

任何状态 → HALTED
HALTED → 只能通过人工恢复程序进入 PAPER 或原低风险状态
```

禁止通过修改环境变量直接从研究模式跳到实盘。

---

# 3. 技术栈与版本策略

## 3.1 Python 与依赖管理

默认选择：

```text
Python: 3.13.x
包管理与锁定: uv
格式化/静态检查: Ruff
类型检查: Pyright 严格模式；必要时补充 mypy
测试: pytest + hypothesis + pytest-asyncio
数据模型: Pydantic v2
日志: structlog / 标准 JSON logging
```

Python 3.14 作为候选升级版本。`P00` 必须执行依赖兼容矩阵；只有核心库、GPU 训练、NautilusTrader、数据库驱动和测试均通过时才能采用 3.14。不得为了“最新”牺牲可重复性或实盘稳定性。

## 3.2 事件驱动交易与回放内核

首选：**NautilusTrader 最新稳定、非预发布版本**，但必须满足：

- 通过本项目领域契约测试；
- 支持选定 Python 版本；
- Binance 路径先通过历史回放、Testnet 和故障测试；
- 订单、成交、账户和精度语义与交易所官方文档一致；
- 版本锁定且有升级回滚方案。

如果当前最新大版本仍为 RC、Beta 或 Alpha，**实盘不得采用预发布版**。使用最新 GA 稳定版，或在本项目领域层后使用自建适配器。NautilusTrader 是实现组件，不是领域事实来源。

研究层同时保留：

- 向量化回测：Polars/NumPy；
- 查询和探索：DuckDB；
- 列式交换：PyArrow；
- 事件回放：NautilusTrader 或符合相同协议的内核。

禁止将 Backtrader、Zipline、Freqtrade 或 CCXT 的默认撮合结果当作权威研究结果。它们可以用于交叉验证或参考，不作为核心实盘内核。

## 3.3 机器学习与研究

```text
scikit-learn
LightGBM
CatBoost
XGBoost
PyTorch
Optuna
MLflow
statsmodels
arch
hmmlearn 或等价可审计实现
SHAP（仅用于分析，不作为因果证明）
```

深度时序和基础模型按插件方式接入，不作为项目启动依赖。候选包括 Chronos-2、Moirai 2、TimesFM 3、Kronos 及后续模型，必须接受统一基准。

## 3.4 存储与数据库

首版：

```text
不可变数据湖: Parquet + PyArrow/Polars
本地分析: DuckDB（锁定当前稳定或 LTS 版本）
权威操作数据库: PostgreSQL
时序扩展: TimescaleDB，可选但推荐
缓存/短期流: Redis，仅在确有需要时启用
对象存储: 本地文件系统；远程部署可用 S3 兼容存储
```

ClickHouse 的引入条件：

- PostgreSQL/TimescaleDB 与 Parquet 查询在真实负载下无法达到页面和回放 SLO；
- 已有可重现基准报告；
- 明确数据重复、备份和运维成本；
- 有双写/迁移验证方案。

在此之前禁止引入 ClickHouse。Redis 不能保存权威订单、余额、仓位、账本或阶段状态。

## 3.5 后端与任务系统

```text
Read/API: FastAPI
ASGI: Uvicorn；生产可配合 Gunicorn 或等价进程管理
数据库: SQLAlchemy 2 + Alembic 或等价严格迁移栈
后台任务: 首版使用数据库任务表 + 受控 Worker
调度: APScheduler 或显式调度服务
事件发布: PostgreSQL Outbox
```

只有在进程数量、吞吐或故障隔离数据证明必要时，才评估 NATS JetStream。首版禁止无依据引入 Kafka。

## 3.6 Web 前端

默认：

```text
Node.js: 24 LTS
包管理: pnpm
框架: Next.js 16 App Router
UI: React 19.2 + TypeScript strict
样式: Tailwind CSS 4
组件: shadcn/ui，采用当前稳定默认底层组件体系
市场图表: TradingView Lightweight Charts 5.2+
分析图表: Apache ECharts 6+
服务器状态: TanStack Query v5
表格与虚拟化: 当前稳定版 TanStack Table / Virtual
表单和验证: React Hook Form + Zod
组件开发: Storybook
测试: Vitest + Testing Library + Playwright
```

所有精确版本由 `P00` 获取官方稳定版本并锁定。不得使用 `latest` 浮动标签进入生产。

## 3.7 可观测性

```text
指标: Prometheus
仪表盘与运维查询: Grafana
日志: Loki
采集代理: Grafana Alloy
追踪: OpenTelemetry；需要时接 Tempo
告警路由: Alertmanager
错误追踪: 可选 Sentry，自托管或受控云服务
```

Promtail 已结束支持，不得新建 Promtail 方案。Grafana 是运维可观测性界面，不替代主业务看板。

## 3.8 部署与开发环境

开发：

```text
Windows 10/11
WSL2 Ubuntu LTS
Docker Desktop / Docker Engine
NVIDIA Container Toolkit（仅需要 GPU 容器时）
```

生产 Paper/Testnet/Live：

```text
独立 Linux LTS 主机或 VPS
系统服务或 Docker Compose
只开放必要端口
反向代理 + TLS
密钥与研究环境隔离
NTP/chrony 时间同步
加密备份
```

首版不使用 Kubernetes。只有在多个独立交易节点、自动容灾和团队运营成为真实需求后才能评估。

## 3.9 技术选型参考但不直接复制

必须研究并记录可借鉴模式：

| 项目/平台 | 学习目标 |
|---|---|
| NautilusTrader | 事件驱动、确定性回放、研究到实盘语义一致性、订单与风险状态机 |
| QuantConnect LEAN | 多资产数据归一化、Brokerage Adapter、算法生命周期 |
| Microsoft Qlib | 数据集、特征、模型、记录器与 AI 研究工作流 |
| VeighNa | 事件引擎、网关、订单管理和中文量化工程经验 |
| Hummingbot | Connector、账户聚合、机器人状态与 API 架构 |
| Freqtrade/FreqUI | 策略运行、回测展示和 Web 交互模式 |
| OpenBB Workspace | 金融工作区、布局、小部件和参数联动 |
| Grafana | 运维可观测性、告警和 Dashboard-as-Code |

每项输出 `knowledge/framework_reviews/<name>.md`，至少包含：可采用、不可采用、许可证、边界、与 AegisQuant 的差异、是否写 ADR。

## 3.10 版本与升级政策

- 所有依赖必须锁定到精确版本并保存 lockfile。
- 每次升级先在副本环境运行全量契约、回放、账本和前端视觉回归测试。
- 交易所 API 与规则变化需要独立 Changelog Watcher。
- 依赖安全更新不得绕过验证直接部署交易进程。
- 核心依赖必须支持一键回滚到上一通过版本。
- 每个季度生成 `reports/dependencies/QUARTERLY_REVIEW_YYYY_QN.md`。

---

# 4. 推荐仓库结构

```text
AegisQuant/
├── README.md
├── CODEX_BOOTSTRAP.md
├── LICENSE_POLICY.md
├── SECURITY.md
├── CONTRIBUTING.md
├── Makefile
├── pyproject.toml
├── uv.lock
├── package.json
├── pnpm-workspace.yaml
├── pnpm-lock.yaml
├── docker-compose.yml
├── .editorconfig
├── .gitignore
├── .gitattributes
├── .pre-commit-config.yaml
├── apps/
│   └── web/
│       ├── app/
│       ├── components/
│       ├── features/
│       ├── lib/
│       ├── public/
│       ├── stories/
│       └── tests/
├── src/
│   └── aegisquant/
│       ├── domain/
│       │   ├── ids/
│       │   ├── time/
│       │   ├── money/
│       │   ├── instruments/
│       │   ├── events/
│       │   ├── forecasts/
│       │   ├── signals/
│       │   ├── portfolio/
│       │   ├── risk/
│       │   ├── orders/
│       │   ├── ledger/
│       │   └── exceptions/
│       ├── data/
│       │   ├── providers/
│       │   ├── adapters/
│       │   ├── schemas/
│       │   ├── lakehouse/
│       │   ├── quality/
│       │   ├── point_in_time/
│       │   └── catalogs/
│       ├── features/
│       ├── labels/
│       ├── research/
│       │   ├── hypotheses/
│       │   ├── datasets/
│       │   ├── experiments/
│       │   ├── validation/
│       │   ├── models/
│       │   └── reports/
│       ├── strategies/
│       │   ├── specs/
│       │   ├── primitives/
│       │   ├── sleeves/
│       │   └── registry/
│       ├── backtest/
│       │   ├── vector/
│       │   ├── event/
│       │   ├── costs/
│       │   ├── fills/
│       │   ├── margin/
│       │   └── metrics/
│       ├── portfolio/
│       ├── risk/
│       ├── execution/
│       │   ├── adapters/
│       │   ├── state_machine/
│       │   ├── algos/
│       │   ├── reconciliation/
│       │   └── recovery/
│       ├── accounting/
│       ├── intelligence/
│       │   ├── source_policies/
│       │   ├── collectors/
│       │   ├── discovery/
│       │   ├── archive/
│       │   ├── normalization/
│       │   ├── language/
│       │   ├── multimodal/
│       │   ├── entity_linking/
│       │   ├── claims/
│       │   ├── event_graph/
│       │   ├── narratives/
│       │   ├── credibility/
│       │   ├── manipulation/
│       │   ├── impact/
│       │   ├── prompt_safety/
│       │   ├── static_analysis/
│       │   ├── extraction/
│       │   ├── lineage/
│       │   └── translation/
│       ├── readmodels/
│       ├── api/
│       ├── workers/
│       ├── observability/
│       ├── security/
│       └── cli/
├── services/
│   ├── api/
│   ├── collector/
│   ├── event_intelligence/
│   ├── research_worker/
│   ├── signal_service/
│   ├── risk_service/
│   ├── execution_service/
│   ├── reconciler/
│   └── scheduler/
├── configs/
│   ├── base/
│   ├── environments/
│   ├── exchanges/
│   ├── data_sources/
│   ├── strategies/
│   ├── models/
│   ├── risk/
│   └── dashboard/
├── migrations/
├── infra/
│   ├── docker/
│   ├── compose/
│   ├── grafana/
│   ├── prometheus/
│   ├── alloy/
│   ├── alertmanager/
│   ├── reverse_proxy/
│   ├── systemd/
│   └── backup/
├── data/
│   ├── raw/
│   ├── bronze/
│   ├── silver/
│   ├── gold/
│   ├── manifests/
│   ├── quarantine/
│   └── catalogs/
├── knowledge/
│   ├── sources/
│   ├── news_archive/
│   ├── social_archive/
│   ├── event_graph/
│   ├── source_policies/
│   ├── joinquant_exports/
│   ├── papers/
│   ├── repositories/
│   ├── framework_reviews/
│   └── rights/
├── experiments/
├── models/
├── reports/
├── state/
├── scripts/
├── notebooks/
│   └── exploratory_only/
└── tests/
    ├── unit/
    ├── property/
    ├── contract/
    ├── integration/
    ├── replay/
    ├── accounting/
    ├── risk/
    ├── execution/
    ├── chaos/
    ├── security/
    ├── performance/
    └── e2e/
```

### 4.1 目录规则

- `src/aegisquant/domain` 不得依赖 FastAPI、数据库 ORM、交易所 SDK 或前端。
- `services/*` 是可执行入口，不承载核心业务规则。
- `notebooks/` 只能探索；任何晋升结果必须迁移到可测试模块。
- `data/raw`、`bronze` 和外部资料归档默认追加写，不原地修改。
- `models/` 只保存登记后的工件引用和小型元数据；大型权重使用对象存储或受控缓存。
- `configs/` 不含秘密。
- `reports/` 和 `state/` 必须可被 CI 验证。


---

# 5. 统一领域模型与不变量

## 5.1 时间模型

任何市场、研究、交易和知识对象都必须区分：

```text
event_time       事件在来源系统发生的时间
available_time   当时首次可被本系统合法获得的时间
ingest_time      本系统实际接收或导入时间
processed_time   当前处理步骤完成时间
revision_time    来源对历史值修订的时间，可为空
```

规则：

- 内部存储统一使用有时区的 UTC 时间戳。
- 不允许使用无时区 `datetime`。
- 回测只能使用 `available_time <= decision_time` 的记录。
- 宏观和链上修订数据必须保存 vintage，不得用最新版覆盖历史视图。
- K 线结束时间与可用时间分开；不能在 K 线未结束时使用完整收盘信息。
- 交易所服务器时间与本地单调时钟都要采集。
- 记录网络延迟和时钟偏差；偏差超阈值触发数据降级或停机。
- 用户展示时才转换为 Asia/Tokyo 或配置时区。

## 5.2 标识符

必须定义强类型标识符：

```text
EventId
RunId
DatasetId
FeatureSetId
LabelSetId
ModelId
ModelVersionId
StrategyId
StrategyVersionId
SignalId
ProposalId
RiskDecisionId
OrderIntentId
ClientOrderId
VenueOrderId
FillId
LedgerEntryId
IncidentId
ProviderId
SourceDocumentId
ArtifactId
```

要求：

- 外部 ID 与内部 ID 分开。
- 幂等键可由确定性命名空间 UUID 或内容哈希生成。
- 重放同一事件不得生成第二笔经济事实。
- ID 不依赖可变数据库自增序号表达跨系统身份。

## 5.3 合约与符号主数据

统一 `Instrument` 至少包含：

```yaml
instrument_id: "BINANCE:PERP:BTCUSDT"
venue: "BINANCE"
venue_symbol: "BTCUSDT"
asset_class: "CRYPTO"
instrument_type: "SPOT|PERPETUAL|FUTURE|OPTION"
base_asset: "BTC"
quote_asset: "USDT"
settlement_asset: "USDT"
contract_size: "1"
linear_inverse: "LINEAR|INVERSE|NA"
price_tick: "0.10"
quantity_step: "0.001"
min_quantity: "0.001"
min_notional: "5"
max_quantity: null
expiry_time: null
strike: null
option_type: null
status: "TRADING"
valid_from: "..."
valid_to: null
source_snapshot_id: "..."
```

必须保存交易规则的**时点版本**。回测历史订单时使用当时有效的 tick size、step size、最小名义金额、杠杆档位和交易状态，而不是当前规则。

建立规范化符号层：

```text
CanonicalAsset: BTC
CanonicalPair: BTC/USDT
VenueInstrument: BINANCE:PERP:BTCUSDT
SyntheticExposure: BTC_USD_DELTA
```

跨交易所比较必须显式处理报价资产、稳定币、结算方式、指数、合约乘数和逆向合约。

## 5.4 数值规则

- 订单价格、数量、金额、手续费、资金费率现金流和账本余额使用 `Decimal` 或定点整数。
- 模型训练和大规模矩阵计算可以使用浮点，但进入订单、风险和会计边界时必须显式量化和验证。
- 所有舍入使用交易所规则驱动，不得用 `round()` 猜测。
- 每个数值字段附单位；禁止无单位的 `value`。
- 百分数在内部使用小数，例如 `0.01 = 1%`。
- 资产数量与法币/稳定币金额不可混用。
- NaN、Infinity 和负零不得进入交易命令或账本。

## 5.5 核心事件和对象

### 5.5.1 `ForecastBundle`

```yaml
forecast_id: "..."
model_version_id: "..."
instrument_id: "..."
as_of_time: "..."
horizon: "5m|1h|4h|1d"
target: "net_return|volatility|tail_loss|fill_probability|slippage"
distribution:
  mean: 0.0
  std: 0.0
  quantiles:
    q05: 0.0
    q50: 0.0
    q95: 0.0
probabilities:
  up: 0.0
  flat: 0.0
  down: 0.0
calibration_version: "..."
uncertainty:
  epistemic: 0.0
  aleatoric: 0.0
  ensemble_disagreement: 0.0
regime_id: "..."
feature_snapshot_id: "..."
dataset_manifest_hash: "..."
code_commit: "..."
should_abstain: true
abstain_reason: "..."
```

### 5.5.2 `AlphaSignal`

```yaml
signal_id: "..."
strategy_version_id: "..."
instrument_id: "..."
as_of_time: "..."
valid_until: "..."
expected_gross_return: 0.0
expected_cost: 0.0
expected_net_return: 0.0
expected_risk: 0.0
confidence: 0.0
score: 0.0
direction: "LONG|SHORT|FLAT"
capacity_notional: "0"
source_forecast_ids: []
reason_codes: []
```

信号不得包含“直接下单”语义。

### 5.5.3 `PortfolioProposal`

必须描述：

- 当前组合；
- 建议目标权重和目标暴露；
- 增量交易；
- 预测收益、风险、成本和容量；
- 策略贡献；
- 因子与市场状态暴露；
- 约束余量；
- 置信度和失效时间。

### 5.5.4 `RiskDecision`

```yaml
risk_decision_id: "..."
proposal_id: "..."
decision: "APPROVE|CLIP|REDUCE_ONLY|REJECT|HALT"
approved_targets: []
limit_results: []
reason_codes: []
risk_policy_version: "..."
account_snapshot_id: "..."
expires_at: "..."
```

风险决定不可由策略进程修改。

### 5.5.5 订单对象

区分：

```text
OrderIntent        已通过风险审查的经济意图
OrderCommand       发往某个交易所的具体命令
VenueOrderState    交易所订单事实
FillEvent          成交事实
OrderRecoveryCase  未知状态恢复记录
```

禁止把本地“已发送”当作交易所“已接受”。

### 5.5.6 会计对象

使用双重记账：

```text
JournalEntry
LedgerPosting
Account
AssetBalance
PositionLot
RealizedPnL
UnrealizedPnLProjection
FeeExpense
FundingIncomeExpense
BorrowInterest
Transfer
ReconciliationAdjustment
```

每笔分录借贷必须平衡。对账调整不得静默覆盖历史。

### 5.5.7 外部内容与来源策略对象

每个外部来源必须先绑定机器可执行的 `SourceProcessingPolicy`，没有策略时不得采集或送入 AI：

```yaml
source_policy_id: "x_public_v1"
provider_id: "x"
access_method: "official_api"
approved_use_case: "private_market_event_analysis"
content_scope: "public_posts_allowlist_and_queries"
raw_storage: "ENCRYPTED_LOCAL|METADATA_ONLY|PROHIBITED"
derived_storage: "ALLOWED|AGGREGATE_ONLY|PROHIBITED"
cloud_inference: "ALLOWED|LOCAL_ONLY|PROHIBITED"
foundation_model_training: "PROHIBITED"
fine_tuning: "PROHIBITED|EXPLICIT_APPROVAL_REQUIRED"
display_mode: "REHYDRATE|DERIVED_ONLY|FULL_WHEN_LICENSED"
deletion_sync_required: true
revision_sync_required: true
redistribution: "IDS_ONLY|PROHIBITED|LICENSED"
retention_days: 0
pii_mode: "MINIMIZE_AND_PSEUDONYMIZE"
policy_checked_at: "..."
terms_version_hash: "..."
```

策略引擎必须在采集、归档、云推理、训练、展示、导出和删除各边界执行检查，不允许仅写在文档中。

### 5.5.8 `RawContentEnvelope`

```yaml
content_id: "..."
provider_id: "x|telegram|gdelt|rss|github|youtube|..."
provider_native_id: "..."
source_identity_id: "..."
content_type: "POST|ARTICLE|ANNOUNCEMENT|VIDEO_META|CHANNEL_MESSAGE|RELEASE|FILING"
canonical_url: "..."
author_time: "..."
published_time: "..."
first_observed_time: "..."
available_time: "..."
ingest_time: "..."
modified_time: null
deleted_time: null
language: "zh|en|ja|..."
raw_object_uri: "..."
raw_content_hash: "..."
revision: 1
engagement_snapshot_id: null
source_policy_id: "..."
rights_state: "ALLOWED|LIMITED|UNKNOWN|PROHIBITED"
quality_state: "GOOD|DEGRADED|STALE|INVALID"
```

同一内容的编辑、互动变化、删除和权限变化必须追加新版本或 tombstone，禁止覆盖历史。

### 5.5.9 `ClaimRecord`

```yaml
claim_id: "..."
content_id: "..."
claim_text_normalized: "..."
subject_entity_ids: []
predicate: "..."
object_entity_ids: []
event_type: "..."
assertion_mode: "FACT|FORECAST|OPINION|RUMOR|DENIAL|QUESTION"
polarity: "AFFIRM|NEGATE|UNCERTAIN"
evidence_spans: []
extractor_versions: []
source_independence_group: "..."
credibility_prior: 0.0
novelty_score: 0.0
prompt_injection_flags: []
```

### 5.5.10 `EventCluster` 与证据图

```yaml
event_cluster_id: "..."
event_type: "EXCHANGE_SECURITY_INCIDENT"
status: "RUMOR|EMERGING|CORROBORATED|CONFIRMED|DENIED|RESOLVED"
entity_ids: []
claimed_event_time: "..."
first_observed_time: "..."
last_updated_time: "..."
claim_ids: []
supporting_evidence_ids: []
contradicting_evidence_ids: []
independent_source_count: 0
official_confirmation_ids: []
credibility_score: 0.0
manipulation_risk: 0.0
uncertainty: 1.0
supersedes_event_cluster_id: null
```

独立来源数必须按所有权、转载链和原始出处去重；一百篇转载同一篇稿件只能视为一个来源家族。

### 5.5.11 `NarrativeState`

描述某个叙事或主题的传播状态：

- 主题和实体；
- 首次出现与传播阶段；
- 发帖/文章速度、独立作者数和平台扩散；
- 观点分布、反对证据和可信度加权情绪；
- 互动速度的时点快照；
- 机器人/协调传播风险；
- 是否已被价格提前反映；
- 叙事衰减半衰期和拥挤度。

### 5.5.12 `EventImpactForecast`

```yaml
impact_forecast_id: "..."
event_cluster_id: "..."
as_of_time: "..."
affected_exposure_ids: []
horizons:
  5m:
    return_distribution: {}
    volatility_delta: 0.0
    liquidity_delta: 0.0
    tail_risk_delta: 0.0
  30m: {}
  4h: {}
  1d: {}
  7d: {}
transmission_channels: []
market_already_moved_score: 0.0
corroboration_score: 0.0
source_quality_score: 0.0
novelty_score: 0.0
manipulation_risk: 0.0
model_disagreement: 0.0
evidence_ids: []
model_versions: []
should_abstain: true
abstain_reasons: []
```

事件预测只是 `ForecastBundle` 的一个输入；它不能直接生成订单。

## 5.6 策略规范对象

每个策略版本必须有机器可读 `StrategySpec`：

```yaml
strategy_id: "trend_breakout_v1"
version: "1.0.0"
status: "research_candidate"
objective: "..."
markets: []
required_data: []
features: []
entry_rules: []
exit_rules: []
position_sizing: {}
risk_constraints: {}
rebalance_frequency: "..."
holding_horizon: "..."
cost_model_id: "..."
parameters: {}
parameter_provenance: {}
known_failure_modes: []
source_lineage: []
validation_policy_id: "..."
implementation_commit: "..."
```

自然语言说明只能作为补充，不能代替 `StrategySpec`。

## 5.7 配置与发布对象

配置必须：

- 使用 JSON Schema/Pydantic 验证；
- 支持环境覆盖但不允许未声明字段；
- 记录内容哈希；
- 区分研究、Paper、Testnet、Canary 和 Live；
- 关键风险配置需要签名和双重确认；
- 不含任何秘密值，只引用秘密键名。

每个发布包至少包含：

```text
release_manifest.json
strategy_specs/
model_manifests/
risk_policy.yaml
instrument_scope.yaml
data_dependencies.yaml
config_hashes.json
test_evidence/
rollback_plan.md
expiry.json
signature
```

## 5.8 错误语义

定义稳定错误码，不依赖异常文本：

```text
AQ-DATA-*
AQ-TIME-*
AQ-MODEL-*
AQ-STRATEGY-*
AQ-RISK-*
AQ-ORDER-*
AQ-LEDGER-*
AQ-RECON-*
AQ-PROVIDER-*
AQ-SECURITY-*
AQ-WEB-*
```

错误必须区分：可重试、不可重试、需要对账、需要人工、触发降级、触发停机。

---

# 6. 数据系统、数据平台与固定接入

## 6.1 Provider Registry

所有数据源先登记，后采集。`ProviderRegistryEntry` 至少包括：

```yaml
provider_id: "binance_public"
provider_name: "Binance Official Public API"
provider_type: "exchange|macro|onchain|news|community|vendor|local"
access_method: "rest|websocket|sdk|file|manual_export"
authority_level: "primary|secondary|derived"
license_status: "approved|restricted|unknown|rejected"
credentials_required: false
regions_or_account_constraints: []
rate_limits: {}
latency_expectation_ms: null
revision_policy: "append_revision"
supported_datasets: []
time_semantics_documented: true
retention_policy: "..."
quality_score: null
incremental_value_score: null
status: "candidate|trial|approved|degraded|retired"
owner: "user"
```

数据源不能因“可接入”自动晋升。必须经过：

```text
权限/许可检查
→ 样本采集
→ 时间语义验证
→ 缺口和一致性分析
→ 成本与延迟评估
→ 样本外增量价值消融
→ 正式批准
```

## 6.2 固定数据源优先级

### 6.2.1 P0：立即接入或建立适配器

#### A. 用户本地资产

优先级最高：

- 原始市场数据；
- 历史回测结果；
- 策略源码；
- 参数配置；
- 逐笔成交和净值；
- 失败实验；
- 旧版 `R331`，如果存在并由用户提供。

只能先做只读清点和哈希，不得原地修改。生成：

```text
reports/data/LOCAL_ASSET_INVENTORY.md
reports/data/LOCAL_ASSET_INVENTORY.parquet
reports/data/LOCAL_DUPLICATES.md
reports/data/LOCAL_FORMAT_PROFILE.json
reports/data/LOCAL_INGEST_PROPOSAL.md
```

#### B. 交易所官方公共数据

首批：

```text
Binance
OKX
Bybit
Deribit
```

采集范围按交易所能力：

- instruments / exchange info；
- 现货、永续、期货、期权元数据；
- K 线；
- agg trades / trades；
- L1/L2 盘口与增量序列；
- ticker、mark、index；
- funding rate；
- open interest；
- basis / delivery data；
- liquidation/force order，在官方提供时；
- options greeks、IV、order book，在 Deribit 等提供时；
- 维护、状态和规则变更。

Binance 为首个完整实现；OKX、Bybit、Deribit 在相同接口下逐步接入。市场数据优先使用 WebSocket，REST 用于快照、补洞和对账。官方接口和变更日志是权威来源。

#### C. 宏观与 point-in-time

```text
FRED
ALFRED vintages
```

目标：利率、美元、流动性、风险资产、通胀和宏观事件。任何修订序列都必须保留当时可得版本。

#### D. 免费/低门槛链上与 DeFi

```text
Coin Metrics Community
Dune
DeFiLlama
项目或协议官方数据
```

Dune 查询必须版本化 SQL、查询参数、执行时间和结果哈希。链上确认时间、索引延迟和回填必须记录。

#### E. 全球新闻、官方公告和一手时事

```text
交易所官方公告、状态页和规则变更
项目/协议官方博客、RSS、治理论坛和安全公告
监管机构、法院、中央银行、政府和证券申报系统
GDELT，用于广域事件发现而非事实终审
公开 RSS/Atom 与合法网页变更监控
GitHub Release、Security Advisory、治理和关键仓库事件
```

优先建立“官方事实源目录”，覆盖交易所、稳定币发行方、ETF/资产管理人、主流协议、监管机构、中央银行和关键基础设施。事件源必须区分事件发生、内容撰写、首次发布、首次观察、修改、删除和系统获得时间。任何新闻特征必须防止回填、聚合延迟和事后编辑泄漏。

#### F. X 推文和获授权社交/频道信息

首批适配器与策略：

```text
X API：官方 recent/full-archive search、filtered stream、用户/列表时间线；按当前用量计费和用途审批执行
Telegram：Bot API 仅处理机器人被授权加入的频道；必要时使用用户本人控制的专用研究账号和官方 MTProto/Takeout 能力
Bluesky：Firehose 或 Jetstream，必须允许 Jetstream 接口变化和回补
YouTube：官方 Data/Live Streaming API 的频道、视频元数据和获准直播聊天
GitHub：公开 API/Webhook 的 release、push、discussion、security advisory 和 issue 事件
```

所有来源必须使用 allowlist、官方 API 和 `SourceProcessingPolicy`。禁止抓取私信、受保护账号、未获授权私人群组或绕过平台限制。X、Telegram 和其他社交内容的当前互动数不得用于历史回测，除非保存了当时快照。

### 6.2.2 P1：完成基线后申请试用和二选一评估

#### 结构化实时新闻与事件数据

至少比较一个偏个人/中等预算来源与一个机构级来源，不强制购买：

```text
个人/中等预算候选：Benzinga Crypto News、Event Registry、CryptoPanic
机构级候选：RavenPack/Bigdata.com、LSEG Machine Readable News、其他经正式授权的实时新闻流
```

评估：

- 首发延迟、修订和删除流；
- 原始正文/标题/摘要许可；
- 实体、事件、相关性、可信度、novelty 和情绪字段定义；
- 中文、英文、日文及跨语言覆盖；
- 历史 point-in-time 可用性；
- 与免费官方源、GDELT 和 X 的重复率；
- 对事件风险、波动预测和净交易价值的样本外增量；
- 供应商退出后的降级能力。

#### 历史 Tick/L2

```text
Tardis 或 Kaiko：首期二选一
```

评估：

- 交易所和日期覆盖；
- 原始更新 vs 重建快照；
- 序列号、缺口和恢复；
- 历史合约元数据；
- 下载成本、存储和许可；
- 与官方样本的一致性；
- 对微观结构策略和成本模型的样本外增量价值。

#### 衍生品聚合

```text
CoinGlass
```

只作为多交易所资金费率、OI、强平和衍生品聚合候选。不得替代官方账户、官方成交和官方标记价格。

#### 专业链上

```text
CryptoQuant 或 Glassnode：首期二选一
```

重点比较：

- 地址实体归因方法；
- 指标修订和历史回填；
- 数据延迟；
- 交易所流入流出定义；
- 许可和 API 限额；
- 对基线模型的真实增量。

#### 传统市场辅助

```text
Databento 或其他正规来源
```

仅在研究 CME BTC/ETH、美元、利率、股指或跨资产价格发现时接入。

### 6.2.3 P2：权限或噪声风险较高，后置/默认关闭

- Santiment；
- LunarCrush；
- Reddit：除非获得与实际算法分析用途一致的明确许可，不得用于模型训练；默认只登记来源状态；
- Discord：仅允许安装到用户有权管理或明确获准的服务器，禁止 self-bot、挖掘和抓取；
- 微博：仅使用官方开放平台、获授权供应商或用户主动导出；
- TikTok：研究 API 通常限定合格非商业研究，个人交易系统默认不启用；
- 其他短视频、私域群聊和未授权社交抓取；
- 第二家同类付费供应商；
- 未证明边际价值的替代新闻聚合。

即使获得权限，也必须通过更严格的时间可得性、许可、提示词注入、机器人污染、协调传播、反向因果、隐私和成本消融测试。

## 6.3 数据适配器协议

定义稳定接口，示意：

```python
class DataProviderAdapter(Protocol):
    provider_id: ProviderId

    async def discover_catalog(self) -> DatasetCatalog: ...
    async def fetch_range(self, request: DataRangeRequest) -> AsyncIterator[RawBatch]: ...
    async def stream(self, request: StreamRequest) -> AsyncIterator[RawEvent]: ...
    async def fetch_revisions(self, request: RevisionRequest) -> AsyncIterator[RawBatch]: ...
    async def health(self) -> ProviderHealth: ...
    async def quota(self) -> ProviderQuota: ...
```

适配器必须提供：

- 原始响应归档选项；
- 请求和响应哈希；
- 限频解析；
- 游标、分页和断点续传；
- 可重试错误分类；
- 数据许可标签；
- 时间语义；
- schema 版本；
- `SourceProcessingPolicy` 和用途批准状态；
- 内容修订、删除、下架和 rehydrate 机制；
- 社交互动指标的时间快照语义；
- 观测指标；
- 测试夹具。

## 6.4 交易所适配策略

- 实盘/回放优先通过已通过测试的 NautilusTrader Adapter。
- 同时建立官方 REST/WS 契约测试，验证字段、状态、精度和异常语义。
- 如果 Nautilus Adapter 对某接口缺失或版本滞后，在 AegisQuant 领域层后实现原生 Adapter。
- CCXT 只能用于探索、元数据对照或应急只读研究，不能成为唯一实盘执行通路。
- 每个交易所使用独立子账户或清晰账户范围。
- 地域、账户资格和产品权限必须由用户确认。

## 6.5 分层数据湖

```text
RAW      原始下载文件、原始 API 响应或供应商格式
BRONZE   结构化但未做经济语义修复
SILVER   标准化、去重、对齐、可查询的事件数据
GOLD     point-in-time 特征、标签、训练集和分析读模型
```

规则：

- RAW/BRONZE 追加写，禁止静默覆盖。
- 每次转换是纯函数式任务，记录输入清单、代码和配置。
- 纠错通过新版本和 tombstone/修订表表达。
- Gold 不是事实源；可以全部重建。
- 文件使用 Parquet；压缩、行组和排序按基准确定。
- 大表按 `provider/venue/dataset/instrument/date` 分区，避免过细小文件。

推荐路径：

```text
data/silver/market/trades/
  venue=BINANCE/
  instrument_type=PERPETUAL/
  symbol=BTCUSDT/
  date=2026-08-31/
  part-*.parquet
```

## 6.6 数据清单与可复现性

每个数据集版本必须有清单：

```json
{
  "dataset_id": "...",
  "schema_version": "...",
  "provider_id": "...",
  "time_range": ["...", "..."],
  "available_time_policy": "...",
  "files": [
    {"path": "...", "sha256": "...", "rows": 0, "min_time": "...", "max_time": "..."}
  ],
  "row_count": 0,
  "transform_commit": "...",
  "transform_config_hash": "...",
  "source_request_hash": "...",
  "quality_report_id": "...",
  "created_at_utc": "..."
}
```

任何训练、回测或报告都必须引用不可变 `dataset_id` 和清单哈希。

## 6.7 数据质量门槛

按数据类型执行：

### 通用

- schema 和类型；
- 主键唯一；
- 时间单调性；
- 重复与冲突；
- 缺失率；
- 数值范围；
- 单位和精度；
- 数据新鲜度；
- 来源一致性；
- 修订历史。

### Trades

- 交易 ID 连续性或已知不连续说明；
- 价格、数量正值；
- maker/taker 语义；
- 重复成交；
- 与成交额和 K 线聚合对照。

### Order Book

- 快照与增量序列正确；
- sequence gap 检测；
- crossed book 检测；
- 价格档位排序；
- 重建后 checksum，若来源支持；
- 断线后的完整重新同步。

### Kline

- 时间区间无重叠；
- OHLC 合法；
- 未结束 K 线明确标记；
- 与 trades 聚合差异在可解释阈值内；
- 缺口不做无痕前向填充。

### Funding/OI/Mark

- 结算周期和发布时间；
- 预估值与最终值分开；
- 修订不能覆盖原始观察；
- 合约和单位一致。

质量失败的数据进入 `data/quarantine`，不得进入 Gold。

## 6.8 Point-in-time 宇宙

任何横截面研究必须构造时点宇宙，包含：

- 上线与下线时间；
- 可交易状态；
- 当时的流动性和历史长度；
- 合约规则；
- 稳定币和报价资产；
- 数据可获得性；
- 交易账户权限；
- 不使用今天仍存续的币种列表回测历史。

退市、合并、重命名、合约迁移和异常状态都必须保留。

## 6.9 数据源增量价值评估

每个付费或复杂数据源必须比较：

```text
Baseline model/strategy
vs
Baseline + candidate source
```

使用相同：

- 样本划分；
- 特征预算；
- 调参预算；
- 随机种子；
- 费用和滑点；
- 交易宇宙；
- 推断延迟假设。

至少报告：

- OOS 预测损失变化；
- 概率校准变化；
- 净 Sharpe/Sortino/回撤变化；
- 换手和容量变化；
- 状态分段表现；
- PBO/DSR 变化；
- 数据成本、许可和运维成本；
- 失败或不可用时的降级路径。

无显著且稳定增量的数据源不得购买长期套餐。

## 6.10 数据访问请求机制

`P00/P02` 必须生成：

```text
reports/access/SOURCE_ACCESS_REQUESTS.md
reports/access/SOURCE_ACCESS_REQUESTS.yaml
reports/access/SECRET_SETUP_GUIDE.md
reports/access/LOCAL_PATH_REQUESTS.md
```

请求按优先级分组，不得索取密码、Cookie、验证码或私钥。可以请求：

- 只读路径；
- API key 的本地秘密名称；
- 订阅层级和额度；
- 账号可用市场；
- 地域与权限限制；
- 手工导出包。

秘密存储优先级：

```text
OS Keyring / Windows Credential Manager
→ Docker Secrets
→ SOPS + age 加密文件
→ 本地受权限保护的环境注入
```

`.env.example` 只放键名和说明，绝不放值。

---

# 7. 外部知识、量化平台与策略情报工程

## 7.1 目标

建立可审计的策略知识库，将论文、开源代码、社区资料、国内量化平台内容和用户旧实验转换为：

```text
可追溯来源
→ 可机器读取的策略规则
→ 静态安全与偏差审计
→ Alpha 原语和谱系
→ 加密市场语义重写
→ 统一回测和样本外验证
```

不能把外部回测收益当作本项目证据，也不能直接执行来源代码。

## 7.2 信息来源优先级

### 一级：正式和可复现来源

- 交易所官方文档、变更日志和状态页；
- 学术论文及其补充材料；
- 作者公开代码仓库；
- NautilusTrader、LEAN、Qlib、VeighNa、Hummingbot、Freqtrade 等成熟框架；
- 用户本地完整数据、代码和失败日志。

### 二级：社区研究

- 聚宽；
- 米筐；
- BigQuant；
- VeighNa 社区；
- 掘金量化；
- 知乎、公众号、知识星球等由用户合法导出的内容；
- 国内外论坛和博客。

### 三级：仅用于线索

- 只有收益截图的帖子；
- 无源码、无规则、无成本的宣传；
- 作者身份和时间不明的转载；
- 社交媒体短帖；
- 无法确定数据可得性的“预测指标”。

## 7.3 聚宽固定接入方案

聚宽采用三通道：

```text
公开搜索索引：发现标题、作者、URL、摘要和关键词
用户手动导出：获取本人有权查看的正文、代码、评论和附件
JQData 官方 SDK：仅获取账号权限覆盖的金融数据
```

重要边界：

- JQData 不等于社区文章 API。
- 当前项目不保存用户聚宽密码、Cookie 或验证码。
- 不建立验证码破解、指纹伪装、代理绕过、批量隐藏接口抓取。
- 浏览器辅助只允许前台可见、用户本人首次登录、域名白名单、低频、只读导出。
- 更推荐本地浏览器扩展：用户打开页面后主动点击“导出当前文章/代码/评论”。
- 所有导出内容仅用于用户个人研究，并记录版权/许可状态。

## 7.4 手工导出包规范

```text
knowledge/joinquant_exports/<source_id>/
├── manifest.yaml
├── page.html
├── article.md
├── code/
│   ├── strategy.py
│   └── notebook.ipynb
├── comments.json
├── attachments/
├── screenshots/
└── checksums.sha256
```

`manifest.yaml` 至少包含：

```yaml
source_id: "jq_<date>_<hash>"
platform: "joinquant"
url: "..."
title: "..."
author: "..."
published_at: null
updated_at: null
exported_at_utc: "..."
export_method: "manual_browser_extension"
user_had_access: true
content_types: []
rights_status: "personal_research_only|public_license|unknown"
original_language: "zh-CN"
notes: ""
```

导入时：

- 计算所有文件 SHA-256；
- 保存原始文件，不覆盖；
- HTML 清洗版本与原始版本分开；
- 附件类型和大小检查；
- 压缩包防路径穿越和压缩炸弹；
- 不加载宏、不执行 Notebook、不导入 Python。

## 7.5 Source Manifest 与证据模型

核心表：

```text
source_manifest
source_artifact
source_version
rights_record
evidence_span
strategy_spec
strategy_relationship
audit_result
translation_record
reproduction_run
```

`evidence_span` 必须把结构化结论链接回原始来源的段落、代码行或附件位置。AI 抽取的规则如果找不到证据，标记 `unsupported`，不能补写事实。

## 7.6 源码静态分析

所有外部代码首先进入隔离目录，只做静态分析：

- Python AST；
- Notebook cell 分离；
- 导入模块；
- 网络、文件、子进程和反序列化调用；
- `eval/exec`；
- 动态导入；
- 凭据访问；
- 可疑删除或覆盖；
- 平台特有 API；
- 全局状态；
- 参数、定时器和回调；
- 数据查询与时间索引；
- 成交函数；
- 调仓和风控逻辑。

危险代码必须隔离并生成：

```text
reports/intelligence/static_analysis/<source_id>.json
reports/intelligence/static_analysis/<source_id>.md
```

只有明确许可、沙箱准备、依赖锁定和审计通过后，才允许在无网络、无秘密、资源受限容器中执行。

## 7.7 策略中间表示 Strategy IR

外部策略必须转换为市场无关 IR：

```yaml
strategy_ir_version: "1"
source_ids: []
universe:
  selection_time: "..."
  eligibility_rules: []
data_requirements: []
features:
  - id: "..."
    formula: "..."
    lookback: "..."
    availability_lag: "..."
signals: []
entries: []
exits: []
position_sizing: {}
rebalance: {}
execution_assumptions: {}
risk_controls: {}
parameters:
  - name: "..."
    value: null
    provenance: "explicit|inferred|missing"
backtest_evidence: {}
known_unknowns: []
```

禁止只生成自然语言摘要。

## 7.8 偏差和欺骗性结果审计

每个来源至少检查：

- 未来函数；
- `available_time` 泄漏；
- 当前成分/币种回测历史；
- 幸存者偏差；
- 数据清洗后视偏差；
- 收盘价信息与成交时点冲突；
- 停牌、涨跌停或不可交易条件被忽略；
- 加密市场中的最小名义、资金费率、借贷、保证金和强平遗漏；
- 手续费、滑点和市场冲击遗漏；
- 只展示最佳参数；
- 未记录试验次数；
- 选择最佳年份或币种；
- 过度参数化；
- 马丁格尔、无限补仓或尾部卖权暴露；
- 资产 Beta 被误认为 Alpha；
- 报告指标计算错误；
- 代码和文章规则不一致。

审计标签：

```text
REPRODUCED
PARTIAL
INFORMATION_MISSING
LEAKAGE
SURVIVORSHIP_BIAS
COST_SENSITIVE
EXECUTION_UNREALISTIC
REGIME_DEPENDENT
DUPLICATE
OVERFIT_RISK
TAIL_RISK_HIDDEN
LICENSE_RESTRICTED
ROBUST_CANDIDATE
REJECTED
```

## 7.9 Alpha 原语与语义去重

建立原语库，例如：

```text
trend_slope
breakout
cross_sectional_rank
short_term_reversal
volatility_scaling
carry
basis_convergence
funding_crowding
term_structure
liquidity_imbalance
order_flow_pressure
open_interest_change
liquidation_shock
seasonality
event_surprise
regime_filter
risk_overlay
```

去重层级：

1. 文本/代码哈希；
2. 归一化 AST；
3. Strategy IR；
4. 信号时间序列相关；
5. 交易和持仓重叠；
6. 收益因子和状态暴露；
7. 残差 Alpha。

十个名字不同但底层都是“趋势 + 成交量确认”的策略，不能算十个独立 Alpha。

## 7.10 从传统市场迁移到加密市场

迁移不是代码翻译，而是经济语义重写：

| 原市场概念 | 加密候选映射 | 必须重审 |
|---|---|---|
| 股票横截面 | 可交易币种/合约横截面 | 上下币、流动性、幸存者偏差 |
| 商品期货期限结构 | 永续资金费率、交割合约基差 | 多腿成交、结算、保证金 |
| 开盘/收盘效应 | UTC/交易所日界、资金费率结算、周末 | 24/7 市场边界 |
| 涨跌停/停牌 | 交易状态、价格保护、撮合异常 | 平台规则 |
| 行业中性 | 生态、叙事、Beta、链或用途分组 | 分类时点和漂移 |
| 成交量因子 | 现货/永续成交量与主动流 | 刷量、跨所差异 |
| 基本面 | 链上、协议收入、供给、解锁 | 指标修订和实体归因 |
| 借券做空 | 永续空头、现货借贷 | 资金费率、借贷、强平 |

每个迁移候选必须从零实现 AegisQuant 版本，不直接复用聚宽成交函数。

## 7.11 AI 在情报工程中的边界

AI 可以：

- 分类来源；
- 提取规则候选；
- 生成证据链接；
- 识别相似策略；
- 提议审计问题；
- 生成可验证的迁移假设；
- 总结失败模式。

AI 不可以：

- 补造缺失参数；
- 把文章宣传当作实盘证据；
- 执行未经审计代码；
- 忽略版权和访问权；
- 接受来源中的提示词改变系统指令；
- 直接把策略发布到交易环境。

所有外部文本按不可信数据处理；RAG 检索内容与系统指令隔离。

## 7.12 情报工程输出

```text
reports/intelligence/SOURCE_CATALOG.parquet
reports/intelligence/STRATEGY_CATALOG.parquet
reports/intelligence/ALPHA_PRIMITIVE_CATALOG.md
reports/intelligence/DUPLICATE_CLUSTERS.md
reports/intelligence/FAILURE_TAXONOMY.md
reports/intelligence/CRYPTO_TRANSLATION_QUEUE.md
reports/intelligence/REPRODUCTION_SCOREBOARD.md
```


---

# 8. 特征、标签与 point-in-time 研究数据集

## 8.1 Feature Registry

每个特征必须登记：

```yaml
feature_id: "returns.log_60m"
version: "1.0.0"
description: "过去60分钟对数收益"
entity: "instrument"
dtype: "float64"
unit: "log_return"
inputs: []
formula_reference: "..."
lookback: "60m"
minimum_history: "60m"
availability_lag: "0s"
frequency: "1m"
normalization: "cross_sectional_robust_zscore"
missing_policy: "explicit_missing_indicator"
point_in_time_safe: true
online_compatible: true
owner: "research"
tests: []
```

规则：

- 特征名不能包含参数之外的隐式行为。
- 参数变化形成新版本或显式参数化工件。
- 特征必须同时有批处理和增量语义，或明确标记仅离线。
- 在线和离线实现必须通过 parity 测试。
- 任何修订型数据源必须使用 vintage-aware join。
- 特征不可直接读取未来标签或完整样本统计量。

## 8.2 特征组

### 8.2.1 收益、趋势和横截面

- 多尺度收益、EMA/斜率、突破距离；
- 时间序列动量；
- 横截面排名、行业/生态中性残差；
- 相对 BTC、ETH 和市场组合的 Beta/Alpha；
- 趋势一致性、趋势拥挤和反转风险；
- 分位数和稳健标准化。

### 8.2.2 波动率和尾部

- realized variance/volatility；
- bipower variation、jump proxy；
- downside/upside semivariance；
- 波动率期限结构；
- 偏度、峰度、分位数和极值；
- drawdown、underwater duration；
- 波动率状态和相关性跃迁。

### 8.2.3 流动性和市场微观结构

- bid-ask spread；
- microprice；
- order book imbalance；
- queue/深度斜率；
- trade sign imbalance；
- VPIN 类指标，仅在定义和时间语义可靠时；
- 价格冲击和恢复；
- Kyle lambda/Amihud 类流动性代理；
- 取消率、补单率、成交簇；
- 跨所 lead-lag；
- 短时延波动与流动性枯竭。

### 8.2.4 衍生品

- 资金费率水平、变化和跨所离散；
- 现货—永续基差；
- 交割合约年化基差和期限结构；
- OI 变化、价格—OI 联合状态；
- 强平冲击；
- mark-index 偏离；
- 预估资金费率与最终结算差异；
- 期权 IV、skew、term structure、put-call 和 gamma 暴露候选。

### 8.2.5 链上和协议

- 交易所净流入；
- 活跃地址、交易量、费用、供应变化；
- 稳定币供给与桥流；
- 协议 TVL、收入和利用率；
- 解锁、发行、质押和赎回；
- 矿工/验证者相关指标；
- 数据实体归因置信度和修订标记。

### 8.2.6 宏观和跨资产

- 利率、收益率曲线、美元、流动性代理；
- 股指、波动率指数、黄金、能源和信用；
- CME BTC/ETH 价格发现；
- 宏观 surprise，必须使用当时预期和首次发布值；
- 风险偏好和相关性状态。

### 8.2.7 新闻、公告、推文和事件

- 上币、下币、合约规则、维护、暂停充提和交易所健康；
- ETF、监管、诉讼、执法、制裁、税务和政策变化；
- 协议升级、漏洞、攻击、治理、解锁、发行、回购和团队变化；
- 宏观数据、中央银行、地缘政治、能源、科技和风险资产事件；
- X/Telegram/Bluesky/YouTube/GitHub 的实体定向内容和传播速度；
- claim 支持/反驳、官方确认、来源独立性、转载链和叙事拥挤；
- 目标实体的 stance，而不是整篇文档的粗糙正负情绪；
- 事件类型、方向、影响通道、时间尺度、不确定性和来源可信度；
- 发帖速度、独立账号数、跨平台扩散、互动速度的时点快照；
- 机器人/协调传播、冒充、被盗账号和信息操纵风险；
- 价格是否已经先行、首次观察延迟和信息半衰期；
- 文本/图片/音频/视频 embedding 只能来自当时合法可获得内容；
- LLM 输出必须链接证据片段、模型版本、冲突来源和置信度。

## 8.3 Feature Snapshot

每次决策读取不可变 `FeatureSnapshot`：

```yaml
feature_snapshot_id: "..."
entity_id: "..."
as_of_time: "..."
feature_set_id: "..."
values_uri: "..."
missing_flags: []
source_dataset_ids: []
watermark_time: "..."
quality_state: "GOOD|DEGRADED|STALE|INVALID"
```

模型不得自由查询数据库拼接未登记特征。

## 8.4 标签体系

标签必须匹配真实可交易目标，而不是只预测裸收益。

### 8.4.1 方向和收益分布

- 未来中间价/可成交价收益；
- 扣除预计成本后的净收益；
- 三分类 `UP/FLAT/DOWN`，平坦区由成本和风险阈值定义；
- 多分位数收益；
- 横截面排名；
- future maximum favorable/adverse excursion。

### 8.4.2 波动率和尾部

- realized volatility；
- 下行半方差；
- 未来分位数损失；
- tail event probability；
- 最大回撤/跳跃风险；
- 相关性和流动性状态切换。

### 8.4.3 衍生品和 Carry

- 未来资金费率现金流；
- 基差收敛；
- 期限结构变化；
- OI/强平状态；
- 现货—永续对冲后的净 Carry。

### 8.4.4 执行标签

- 限价单在给定时间内的成交概率；
- 成交比例；
- 实际滑点；
- adverse selection；
- 撤单后成交风险；
- 市场冲击和恢复时间；
- 多腿交易裸露时间。

## 8.5 标签生成不变量

- 标签窗口与特征窗口严格分离。
- Purge 长度覆盖最大标签跨度。
- 费用、资金费率和可成交价格在标签中有明确版本。
- 不把未来最佳入场价作为可用标签直接训练决策。
- 重叠标签必须在统计检验和样本权重中处理。
- 标签分布、平衡和状态漂移必须报告。

## 8.6 训练集清单

任何训练集必须生成：

```text
Dataset Manifest
Feature Set Manifest
Label Set Manifest
Universe Manifest
Split Manifest
Cost Assumption Manifest
Data Quality Report
Leakage Audit
```

没有这些工件，训练任务拒绝启动。

---

# 8A. 全球事件、新闻、公告与社交媒体 AI 联合判断

## 8A.1 不可妥协的定位

AegisQuant 禁止成为“只看 K 线的预测器”。价格、成交、盘口和衍生品信息反映市场行为；新闻、公告、推文、频道消息、监管动作和协议活动描述潜在原因与未来风险。两类信息必须在 point-in-time 条件下联合判断。

系统必须同时保留三种结论：

```text
MARKET_ONLY_VIEW      仅由市场数据支持的判断
EVENT_ONLY_VIEW       仅由事件证据支持的判断
FUSED_VIEW            两者融合后的条件预测
```

任何研究报告都必须说明事件数据带来了什么增量；若没有增量，系统仍需保留事件风险监控，但不得强行将其用于方向交易。

## 8A.2 来源优先级与信任层级

来源层级不是永久真理，而是先验；后验可信度必须按事件类别和历史表现更新。

### Tier A：一手权威

- 交易所公告、状态页、规则和账户事实；
- 项目、基金会、稳定币发行方、托管方和审计方官方渠道；
- 监管机构、法院、政府、中央银行和证券申报；
- 代码仓库 Release/Security Advisory 和链上可验证交易；
- 明确签名或可验证域名控制的官方声明。

### Tier B：授权专业新闻

- 正规新闻通讯社和财经新闻流；
- 具有修订、删除和时间戳语义的授权结构化新闻供应商；
- 原始记者稿而非转载聚合。

### Tier C：可归因专业人士和组织

- 已验证且能与官方网站交叉验证的项目负责人、研究员、律师、记者、政策人物；
- 其可信度按事件领域分别评分，不能因粉丝数直接提高。

### Tier D：公开社区与匿名社交

- 普通 X 帖子、Telegram 公共频道、Bluesky、论坛和评论；
- 只作为早期线索、叙事强度和传播结构，不作为单独事实确认。

### Tier E：聚合、截图和无法追溯内容

- 截图、转述、匿名爆料、无原始链接的短视频；
- 默认高不确定性，不得触发方向仓位；仅可触发查证任务或风险关注。

## 8A.3 固定接入矩阵

### X

使用官方 X API：

- filtered stream 用于实时关键词、cashtag、账户和列表监控；
- recent search 用于补洞；
- full-archive search 用于许可范围内的历史重放；
- user/list timelines 用于官方账号和专家 allowlist；
- engagement、edit history 和 conversation graph 只按当时快照使用。

当前接入按用量计费，P00/P04 必须读取开发者控制台的实际价格、额度和已批准 use case。不得使用网页抓取、共享 Token、受保护内容或规避限额。离线存储、展示、删除和修改同步必须服从当前 X Developer Agreement/Policy。

### Telegram

- Bot API 仅收集机器人被明确添加且获授权的频道/群组消息；
- 对公开频道历史的更深接入，只能使用用户本人控制的专用研究账号和官方 MTProto/Takeout 能力；
- 必须有频道 allowlist、会话加密、登录人工完成、撤销和导出审计；
- 禁止读取私人聊天、未授权群组或将会话文件提交到 Git。

### Bluesky / AT Protocol

- 支持 Firehose；Jetstream 可作为低带宽 JSON 路径；
- Jetstream 不视为永久稳定协议，必须有版本探测、断点和 Firehose 回退；
- 使用 DID 而非显示名做身份主键。

### YouTube

- 官方 Data API 获取频道、视频、直播和元数据；
- Live Streaming API 在权限允许时获取直播聊天；
- 只使用 API 明确提供或用户有权提供的字幕/转录；禁止通过未授权抓取构建转录库；
- 视频本体默认只保存 URL、ID、缩略元数据和合法派生结果。

### GitHub

- 对关键协议、客户端、交易所 SDK 和基础设施仓库使用 Webhook/API；
- 监控 release、tag、security advisory、push、discussion、issue 和维护者公告；
- 提交活动不自动等于基本面改善，必须经过实体和事件语义解释。

### 新闻与网页

- RSS/Atom、官方 API、GDELT、Event Registry 等合法接口优先；
- 网页变化监控必须尊重 robots、条款、限频和许可；
- 聚合站只用于发现，最终事实尽量回到原始来源。

### 默认关闭来源

- Reddit、Discord、微博、TikTok 和其他平台只有在用途、权限、保留、模型处理与展示规则明确后启用；
- 禁止使用 self-bot、登录态劫持、验证码绕过、移动端逆向或隐藏接口。

## 8A.4 事件本体

至少覆盖：

```text
MACRO_DATA_RELEASE
CENTRAL_BANK_DECISION
REGULATION_POLICY
ENFORCEMENT_LAWSUIT
ETF_FILING_APPROVAL_FLOW
EXCHANGE_LISTING_DELISTING
EXCHANGE_OUTAGE_WITHDRAWAL_HALT
EXCHANGE_SOLVENCY_RUMOR
SECURITY_EXPLOIT_HACK
STABLECOIN_DEPEG_RESERVE
PROTOCOL_UPGRADE_FORK
TOKEN_UNLOCK_ISSUANCE_BURN
GOVERNANCE_PROPOSAL_VOTE
PARTNERSHIP_ADOPTION
TREASURY_BUY_SELL
MINER_VALIDATOR_EVENT
KEY_PERSON_CHANGE
LEGAL_BANKRUPTCY
GEOPOLITICAL_RISK
ENERGY_TECH_RISK_ASSET_SHOCK
MARKET_MANIPULATION_RUMOR
MISINFORMATION_DENIAL
```

每个事件类型必须定义：

- 必需实体和字段；
- 何种来源可确认；
- 可能影响的资产与传导通道；
- 预期时间尺度；
- 常见反向因果；
- 允许的风险动作；
- 回测标签和评估指标。

## 8A.5 时间、修订和删除语义

每条内容至少保留：

```text
claimed_event_time
content_created_time
first_published_time
first_observed_time
available_time
provider_received_time
ingest_time
modified_time
deleted_time
engagement_observed_time
```

要求：

1. `available_time` 是策略当时真正可使用的最早时间，不等于页面显示发布时间。
2. 聚合新闻的 `first_observed_time` 不能倒推为原始媒体发布时间。
3. 互动数、浏览量、点赞、转发和回复必须作为时间序列快照。
4. 编辑和删除不能覆盖原始版本；使用 revision + tombstone。
5. 历史回测不得使用今天的认证状态、粉丝数、简介、互动总数或最终事实标签。
6. 来源身份和官方归属也必须版本化。

## 8A.6 内容安全与规范化

外部内容进入模型前：

```text
接收原始对象
→ 许可和用途检查
→ 哈希、签名/域名、MIME 和恶意文件检查
→ HTML/Markdown/Unicode 规范化
→ 提示词注入隔离
→ 语言识别
→ 原文保留 + 可审计翻译
→ 近重复/转载检测
→ 实体链接
→ Claim 抽取
```

要求：

- 外部文本永远位于 data channel，不能覆盖 system/developer 指令；
- URL 不能由 LLM 自主访问，只能提交给受限 Fetcher；
- 附件和压缩包进入沙箱；
- 翻译不得替代原文，需保存翻译模型和置信度；
- 对表情、cashtag、hashtag、引用、回复、转发和链接展开建立结构化字段；
- 图像 OCR、图表理解、语音转写和视频帧分析仅在许可允许时进行，并保存原始证据坐标和模型版本；
- 不允许因模型看不到内容而编造摘要。

## 8A.7 AI 联合判断流水线

### Fast Path：秒级筛选

使用确定性规则和小模型：

1. 语言与垃圾内容过滤；
2. 实体识别和资产映射；
3. 事件类型粗分类；
4. 近重复和转载家族；
5. 来源先验、官方身份和账户异常；
6. 目标实体 stance；
7. attention velocity、novelty 和异常传播；
8. 与实时价格、成交、OI、资金费率和盘口变化对齐；
9. 触发 `IGNORE / MONITOR / DEEP_ANALYZE / RISK_ESCALATE`。

### Deep Path：证据委员会

对高价值候选并行运行：

- **Extractor Agent**：逐条抽取可验证主张和证据片段；
- **Entity Agent**：链接资产、公司、协议、人物、交易所、司法辖区和合约；
- **Source Agent**：检查身份、所有权、转载链、历史准确性和专业领域；
- **Corroboration Agent**：寻找独立支持和反驳；
- **Skeptic Agent**：主动寻找替代解释、旧闻、讽刺、假账号、被盗账号和价格先行；
- **Market Microstructure Agent**：判断盘口、成交、衍生品是否印证；
- **On-chain Agent**：判断链上事实是否印证；
- **Impact Agent**：输出多资产、多时间尺度概率分布；
- **Policy Agent**：检查许可、隐私和是否允许云端推理；
- **Arbiter**：只基于上述结构化证据合并，不得新增无来源事实。

所有 Agent 输出必须通过 JSON Schema，并包含：

```text
evidence_ids
source_content_ids
reason_codes
uncertainty
missing_evidence
contradictions
model_version
prompt_template_hash
```

### 数值模型与 LLM 的分工

- LLM 负责语义、主张、关系、解释和未知项；
- 统计/树模型负责来源后验、事件响应、传播、市场已反映程度和影响预测；
- 图模型负责证据关系、传播和实体依赖；
- 时间序列模型负责行情与事件上下文融合；
- 规则引擎负责硬风控和官方事件应急动作；
- LLM 永远不能输出 `OrderCommand`。

## 8A.8 可信度、来源独立性和操纵检测

可信度不是单一 `verified` 标记。候选特征包括：

- 官方域名/链上地址/项目网站的交叉链接；
- 账号和域名历史、改名、异常登录或突然风格改变；
- 事件领域内历史 precision、首次报道速度和更正率；
- 原始文件、交易哈希、法庭文件、公告编号和可验证签名；
- 是否只是转载、引用或内容农场；
- 独立来源家族；
- 账户群同步发帖、文本模板相似和异常互动；
- 新账号、低质量关注网络、付费推广和机器人风险；
- 是否与价格先行运动同步，可能只是事后解释。

禁止：

- 对普通用户推断敏感个人属性；
- 把粉丝数、蓝标或互动数等同真实度；
- 公开标记具体用户为“机器人/诈骗者”，除非有平台或权威结论；
- 使用社交数据进行个体画像或站外身份匹配。

## 8A.9 跨源去重、冲突和事件状态机

事件状态：

```text
RUMOR
→ EMERGING
→ CORROBORATED
→ CONFIRMED
→ RESOLVED
```

旁路状态：

```text
DENIED
RETRACTED
STALE
DUPLICATE
MANIPULATED
INSUFFICIENT_EVIDENCE
```

转换必须由证据触发，并记录先前状态。官方否认不总是事实终结，但会显著改变后验。对于相互矛盾的权威来源，系统必须保持冲突状态并降低仓位，不得由 LLM 擅自裁决。

## 8A.10 事件和市场融合特征

至少研究：

- 事件 surprise 和与预期差；
- 事件新颖度、重复度和信息衰减；
- 独立来源数和官方确认延迟；
- 传播速度、跨平台扩散和叙事拥挤；
- 可信度加权 stance；
- 市场已反映程度；
- 事件前异常成交、OI、资金费率、基差和链上流；
- 事件后流动性恶化、价差、强平和跨所离散；
- 资产知识图谱暴露：协议、代币、交易所、稳定币、投资方、桥和依赖；
- 同类历史事件的条件响应分布；
- 事件与当前市场状态交互；
- 传闻被否认后的反转概率；
- 信息源拥挤与 alpha decay。

融合模型必须比较：

```text
Market-only
Event-only
Early fusion
Late fusion / stacking
Risk-only event overlay
```

## 8A.11 事件影响预测目标

对每个受影响暴露和时间尺度预测：

- 扣成本收益分布；
- 实现波动率变化；
- downside/tail 概率；
- spread、depth、impact 和成交概率；
- 资金费率、基差、OI 和强平风险；
- 相关性和 contagion；
- 事件持续、升级、否认和衰减概率；
- `market_already_moved_score`；
- 不交易概率。

不能只训练“情绪正负”。

## 8A.12 决策门控和风险动作

### 方向交易门槛

单一社交帖子永远不足以触发中等以上方向仓位。默认要求：

- 来源许可允许算法分析；
- 至少一个可追溯原始来源；
- 事件和资产映射明确；
- 独立证据、官方证据或市场/链上印证达到策略阈值；
- 预测优势覆盖费用、滑点和事件延迟；
- 模型分歧、操纵风险和 OOD 低于阈值；
- 风险引擎批准。

### 风险覆盖层

即使方向不确定，事件可以触发：

```text
MONITOR_ONLY
NO_NEW_POSITION
REDUCE_POSITION
REDUCE_ONLY
CANCEL_PASSIVE_ORDERS
HEDGE_DELTA
HALT_VENUE
HALT_ASSET
```

例如交易所官方暂停提现、安全攻击或稳定币储备事件，可以先降低交易所/资产暴露；但动作仍由签名风险规则和独立 Risk Engine 执行，不由 LLM 自由决定。

## 8A.13 历史回放与反泄漏

事件回测必须具备：

- 原始内容或许可允许的 ID/快照；
- 首次观察时间和采集延迟；
- 当时可见的来源身份、互动和正文版本；
- 编辑、删除、否认和后续确认；
- 新闻聚合转载链；
- 模型、翻译、事件本体和映射版本；
- 与行情事件的统一时钟和延迟模型。

强制检验：

1. **timestamp perturbation**：轻微延后内容时间，收益不应异常崩塌到暴露泄漏；
2. **pre-trend**：新闻前价格已显著移动时，降低因果解释；
3. **placebo event**：随机替换事件时间/资产；
4. **source-family dedupe**：去除转载后仍应有结论；
5. **engagement snapshot test**：禁止使用未来互动数；
6. **revision test**：首次版本与最终版本分开；
7. **latency stress**：增加 5 秒、30 秒、2 分钟、10 分钟延迟；
8. **cost and liquidity stress**；
9. **narrative regime split**；
10. **event taxonomy holdout**：保留未见事件类型或新实体测试泛化。

没有可靠历史 point-in-time 内容时，只能用于实时风险监控和前瞻 Paper，不得声称历史 Alpha。

## 8A.14 训练、推理和版权边界

每个来源分别声明：

```text
可否保存原文
可否发送云端模型
可否产生 embedding
可否训练分类器
可否微调模型
可否展示原文
可否导出
删除/修改同步要求
保留期限
```

统一原则：

- 不使用 X 内容训练或微调基础/前沿模型；只在已批准 use case 内做分析；
- Reddit 内容默认不得训练模型，除非取得权利人和平台明确许可；
- 受限内容优先本地推理和仅保存派生特征；
- 云模型供应商必须明确不把请求用于训练，且符合来源许可；
- Dashboard 在许可不允许全文展示时，只显示来源 ID、链接、简短自有分析和可重新获取入口；
- 删除和修改请求必须传播到缓存、向量库、搜索索引和展示层。

## 8A.15 人工标注与主动学习

建立小型高质量金标准，而不是依赖自动情绪标签：

- 双人独立标注 + 分歧仲裁；
- 事件类型、实体、主张、stance、可信度、是否已反映、影响方向/时长；
- 标注者只看当时时点信息；
- 主动学习挑选高分歧、高价值和新事件类型；
- 标注指南版本化；
- 不允许用后续价格结果反向修改“事实真伪”标签。

## 8A.16 评估指标

语义层：

- entity linking precision/recall；
- claim extraction F1；
- event clustering pairwise/B-cubed；
- source-family dedupe；
- contradiction detection；
- calibration 和 abstain quality。

时效层：

- first-seen latency；
- official-confirmation lead/lag；
- duplicate suppression；
- deletion/update propagation；
- stream gap recovery。

金融层：

- 多时间尺度 Brier/CRPS；
- 方向和尾部 calibration；
- volatility/liquidity forecast gain；
- risk event recall 和 false halt rate；
- Market-only vs Fused 的 OOS 净增量；
- 延迟和成本压力后的净价值。

系统层：

- 每事件证据完整率；
- 无证据断言率必须接近零；
- 来源政策违规为零；
- 提示词注入越权为零；
- 被删除内容在策略要求时限内清除或 tombstone。

## 8A.17 降级与故障

当 X、新闻供应商或 LLM 不可用时：

```text
事件特征质量标记 DEGRADED
→ 禁止依赖事件的新策略开仓
→ 继续市场数据基线或进入更保守风险状态
→ 保留官方公告和本地缓存
→ 告警并记录缺口
→ 恢复后回补但不得改写历史决策
```

事件智能服务故障不得阻塞账本、撤单、风控和账户对账。

# 9. 自动化研究工厂、实验制度与 AI Model Council

## 9.1 研究原则

系统的核心不是找到一个“永远有效”的模型，而是持续执行：

```text
提出可证伪假设
→ 结构化定义
→ 使用 point-in-time 数据
→ 与简单基线公平比较
→ 严格样本外验证
→ 成本与压力测试
→ 记录所有失败
→ 晋升、降级或淘汰
```

任何研究结果都必须能够说明“新增复杂度带来了什么可重复增量”。

## 9.2 Hypothesis Spec

每个假设必须是机器可读对象：

```yaml
hypothesis_id: "..."
claim: "..."
economic_rationale: "..."
falsification_conditions: []
markets: []
horizons: []
required_data: []
feature_candidates: []
label_id: "..."
baselines: []
metrics: []
validation_policy_id: "..."
compute_budget: {}
search_space: {}
expected_failure_modes: []
source_lineage: []
created_by: "human|ai"
created_at_utc: "..."
```

AI 生成的假设必须经 schema 验证和用户/规则审批后才进入实验队列。

## 9.3 Experiment Ledger

MLflow 或等价 Registry 必须记录**每一次**试验，包括失败和异常：

- Run ID；
- 代码提交；
- 环境和 lockfile 哈希；
- 数据、特征、标签、宇宙和 split 哈希；
- 模型和超参数；
- 随机种子；
- 训练耗时、CPU/GPU/RAM；
- 所有评估指标；
- 成本模型；
- 产物哈希；
- 父实验和搜索任务；
- 是否由 AI 提议；
- 失败原因；
- 晋升决定。

禁止删除差结果来“清理排行榜”。

## 9.4 数据划分与验证

### 9.4.1 Walk-forward

至少包含：

- 扩展窗口；
- 滚动窗口；
- 最近状态窗口；
- 固定最终 holdout。

训练、验证、校准和最终测试时段分开。最终 holdout 在所有模型和参数冻结前不得查看。

### 9.4.2 Purge 和 Embargo

- Purge 覆盖标签重叠窗口。
- Embargo 覆盖临近样本泄漏和再平衡效应。
- 横截面样本按时间组处理，禁止随机行切分。
- 新闻和宏观特征按真实可得时间切分。

### 9.4.3 CPCV/CSCV、PBO 和多重试验

对于大量策略/参数搜索：

- 使用 CPCV/CSCV 或可审计等价流程；
- 估计 Probability of Backtest Overfitting；
- 使用 Deflated/Probabilistic Sharpe 修正选择偏差；
- 使用 FDR、White Reality Check、SPA 或适合的方法处理多重假设；
- 报告总搜索次数，而不是只报告最佳候选。

### 9.4.4 状态分段

至少按以下状态报告：

```text
牛市/熊市/横盘
高/低波动
高/低流动性
正/负资金费率拥挤
周末/工作日
重大事件/正常期
交易所异常期
稳定币压力期
```

状态划分方法本身必须 point-in-time。

## 9.5 永久基线阶梯

任何复杂模型都必须和以下基线比较：

### Level 0：无预测

- 始终现金；
- 等权持有；
- 随机但匹配换手的策略；
- 前值/随机游走；
- 简单波动率缩放。

### Level 1：经典统计

- moving average / breakout；
- AR/ARIMA，仅在适用时；
- Elastic Net / Logistic；
- Kalman filter；
- HAR-RV；
- GARCH 类；
- HMM 或简洁状态模型。

### Level 2：树模型

- LightGBM；
- CatBoost；
- XGBoost。

只有在相同输入、搜索预算、样本切分和成本下胜过基线，复杂模型才保留。

## 9.6 Model Council

### Expert A：方向与横截面基线

- 线性/Logistic/Elastic Net；
- rank regression；
- 稳健分位数回归；
- 简单状态条件模型。

### Expert B：表格非线性模型

- LightGBM；
- CatBoost；
- XGBoost；
- 单调约束和特征交互限制，在经济意义支持时使用。

### Expert C：深度时序模型

候选：

- TCN；
- N-BEATS/N-HiTS；
- PatchTST；
- iTransformer；
- TFT；
- 轻量多尺度 Transformer。

必须限制参数规模，先在少量市场和窗口验证。4070 Ti 的显存和训练时间必须作为真实约束。

### Expert D：时序基础模型

候选插件：

- Chronos-2；
- Moirai 2；
- TimesFM 3；
- Kronos；
- 后续公开且许可允许的模型。

使用规则：

- 先 zero-shot/frozen embedding，再考虑适配；
- 不允许因为论文结果直接晋升；
- 与随机游走、树模型和专用时序模型同样本比较；
- 记录权重许可、下载来源和哈希；
- 云端调用时不得发送账户、订单、密钥或未授权数据；
- 推断延迟和费用进入交易成本。

### Expert E：状态、风险与尾部

- 波动率和流动性状态；
- 极值和尾部概率；
- 相关性结构变化；
- 稳定币/交易所异常；
- 模型失效概率。

### Expert F：多模态事件与证据智能

子专家：

- 多语言实体识别、实体消歧和资产知识图谱；
- Claim 抽取、stance、否认和不确定性；
- 事件分类、聚类、状态机和跨语言去重；
- 来源身份、转载家族、可信度后验和操纵风险；
- X/Telegram/Bluesky/YouTube/GitHub 传播图与 attention velocity；
- 图片、图表、音频和视频的许可受控解析；
- surprise、市场已反映程度和影响窗口；
- 多文档支持/反驳和 Skeptic Agent；
- 事件影响的方向、波动、流动性、基差和尾部预测；
- 提示词注入、版权、隐私和来源政策执行。

Expert F 必须分别输出语义置信度、事实置信度、金融影响置信度和 `ABSTAIN`；不能用一个“情绪分数”代表全部判断。

### Expert G：执行模型

- fill probability；
- slippage；
- adverse selection；
- impact；
- order lifetime；
- maker/taker 选择；
- 多腿执行顺序。

## 9.7 模型输出与训练目标

禁止只优化“涨跌准确率”。按任务使用：

- Log loss/Brier score；
- CRPS；
- pinball/quantile loss；
- calibration error；
- precision/recall at economically actionable threshold；
- rank IC/ICIR；
- volatility forecast loss；
- tail coverage；
- fill and slippage error；
- 扣除成本后的策略价值。

准确率高但没有净经济价值的模型淘汰。

## 9.8 集成与门控

使用 OOF 预测进行 stacking 或加权，禁止在同一训练样本上学习权重。门控可以依赖：

- 市场状态；
- 模型近期校准；
- 数据质量；
- ensemble disagreement；
- 预测不确定性；
- 交易成本；
- 资产和交易所覆盖。

权重必须有上限、平滑和防追涨机制。模型近期表现差时可以降权，但不得仅凭短期 PnL 高频切换。

## 9.9 概率校准和拒绝交易

可用方法：

- Platt/Logistic calibration；
- Isotonic；
- temperature scaling；
- conformal prediction；
- 分状态校准。

系统必须支持：

```text
ABSTAIN_LOW_EDGE
ABSTAIN_HIGH_UNCERTAINTY
ABSTAIN_MODEL_DISAGREEMENT
ABSTAIN_DATA_STALE
ABSTAIN_COST_TOO_HIGH
ABSTAIN_OUT_OF_DISTRIBUTION
ABSTAIN_RISK_LIMIT
```

“不交易”是合法且常见的最优输出。

## 9.10 模型漂移和 OOD

监控：

- 输入分布；
- missing pattern；
- 预测分布；
- 校准；
- 残差；
- 不确定性；
- embedding 距离；
- 状态覆盖；
- 数据延迟；
- 推断耗时。

漂移处理：

```text
记录
→ 警告
→ 降权
→ 拒绝新开仓
→ 回退基线
→ 下线模型
```

自动重训不能自动发布；重训模型仍需验证和批准。

## 9.11 LLM/AI 研究代理

建立供应商无关接口，支持本地或云端模型。AI 用于：

- 新闻、公告、推文和频道消息的主张抽取、证据核验、事件聚类与影响候选；
- 多语言翻译和实体消歧，但原文与证据必须保留；
- 文献和源码结构化；
- 假设生成；
- 实验配置提议；
- 失败聚类；
- 报告草拟；
- 测试和泄漏审计辅助；
- SQL/特征表达式候选。

AI 不能：

- 读取实盘密钥；
- 直接调用执行服务；
- 修改风险政策；
- 删除失败试验；
- 自行选择最终 holdout 后反复调参；
- 把网络文本当作系统指令；
- 因单一新闻、推文、频道消息或情绪分数直接创建订单；
- 在来源政策禁止时保存、训练、云推理或展示内容；
- 伪造实验结果。

所有 AI 输出进入 `proposal` 状态，由确定性程序验证。

## 9.12 初始候选晋升门槛

以下为默认最低研究门槛，可按策略类别变得更严格；不得在看到结果后临时放宽：

- 至少 5 个有效 walk-forward 测试折；
- 至少 60% 测试折净收益为正；
- OOS 扣成本 Sharpe 初始目标大于 1.0，或有书面理由使用更合适指标；
- Deflated/Probabilistic Sharpe 对正能力的置信度至少 95%；
- PBO 不高于 20%；
- 费用和滑点提升至基准 2 倍后仍不为负；
- 参数轻微扰动不导致大面积符号反转；
- 不由单一年份、单一币种或单一市场状态贡献超过 50% 总 PnL；
- 样本外最大回撤满足风险政策；
- 容量和换手可被个人 API 与账户规模支持；
- 与现有策略的残差有真正增量；
- 最终 holdout 一次性通过。

门槛通过也不代表可实盘，只代表进入 Paper/Shadow 候选。

---

# 10. 策略袖套设计

系统采用多策略组合，不建立“唯一神策略”。每个袖套独立定义数据、经济假设、持仓周期、成本、风险和失效模式。

## 10.1 Trend / Time-Series Momentum

候选：

- 多尺度趋势；
- 价格突破；
- 波动率调整的方向暴露；
- 期货和永续趋势；
- 跨市场趋势确认。

防线：

- 避免在流动性枯竭时追价；
- 处理快速反转和震荡损耗；
- 方向暴露上限；
- 趋势拥挤和相关性上升时降杠杆。

## 10.2 Cross-Sectional Relative Value

候选：

- 横截面动量/反转；
- 残差收益；
- 市场/生态/规模中性；
- 多空组合；
- 稳健排序和容量筛选。

防线：

- point-in-time 宇宙；
- 退市和上线偏差；
- 小币种刷量；
- 空头资金费率和可交易性；
- 市场 Beta 与稳定币暴露。

## 10.3 Carry / Basis / Funding

候选：

- 现货—永续 delta-neutral；
- 永续跨所资金费率；
- 交割合约基差收敛；
- 期限结构；
- 期权 Carry，后置。

净收益必须包括：

```text
funding/basis income
- maker/taker fee
- spread/slippage
- borrow interest
- hedging cost
- transfer cost
- margin capital cost
- multi-leg exposure loss
- venue/stablecoin tail risk
```

不得把“市场中性”理解为无风险。

## 10.4 Medium-Frequency Microstructure

候选：

- order book imbalance；
- microprice mean reversion；
- aggressive flow continuation/reversal；
- 跨所价格发现；
- liquidation impulse；
- 短期限价单选择。

先使用历史 L2 和保守模拟验证；没有高质量队列和延迟数据时不得声称做市收益。

## 10.5 Mean Reversion / Liquidity Shock

候选：

- 短期过度反应；
- 跨所短暂偏离；
- 流动性冲击后的恢复；
- 资金费率/基差极端回归。

防线：

- 区分结构性信息冲击；
- 价格限制和交易所异常；
- 止损不是唯一尾部控制；
- 风险状态下可完全禁用。

## 10.6 Breakout / Event / Narrative

候选事件：

- 上币/下币、暂停充提和交易所状态；
- 监管、ETF、诉讼、执法、制裁和政策；
- 安全事故、漏洞、稳定币脱锚和基础设施故障；
- 升级、治理、解锁、发行、销毁和财库交易；
- 关键人物、合作、采用、矿工/验证者和链上异常；
- 中央银行、宏观 surprise、地缘政治和跨资产冲击；
- X/Telegram/Bluesky 等叙事的早期扩散、拥挤和否认反转。

子策略必须明确属于：

```text
CONFIRMED_EVENT_DIRECTIONAL
RUMOR_TO_CONFIRMATION
DENIAL_REVERSAL
ATTENTION_BREAKOUT
EVENT_VOLATILITY
EVENT_LIQUIDITY_DEFENSE
OFFICIAL_RISK_OVERLAY
```

必须建模首次观察时间、数据延迟、来源独立性、价格是否已先行、抢先交易可能性、流动性、操纵风险和后续反转。事后整理的事件数据库、最终互动数和最终新闻版本不能直接用于回测。任何单一社交帖子默认只能进入 `MONITOR` 或极低风险研究信号。

## 10.7 Defensive Overlay

不以赚取 Alpha 为唯一目标：

- volatility target；
- correlation shock deleveraging；
- drawdown control；
- exchange/stablecoin concentration cap；
- tail hedge；
- cash allocation；
- 数据/模型异常时的 exposure decay。

## 10.8 Options Overlay（后置）

只有在 Deribit 数据、希腊值、波动率曲面、保证金和执行模拟成熟后实施：

- volatility risk premium；
- skew/term structure；
- convex hedge；
- delta/gamma/vega 管理。

首版禁止裸卖无上限风险期权。

## 10.9 策略分配原则

每个袖套提交：

- 预期净收益分布；
- 风险和尾部；
- 交易成本；
- 容量；
- 相关性；
- 状态适用性；
- 置信度；
- 失效时间；
- 可撤销性和执行复杂度。

袖套不能直接控制总账户。

---

# 11. 组合构建与仓位计算

## 11.1 输入

组合层读取：

```text
当前权威仓位和现金
已批准信号
预期收益/风险/成本分布
协方差和尾部场景
交易所、资产、稳定币和策略暴露
保证金与流动性
未完成订单和执行裸露
风险政策
```

## 11.2 优化目标

默认目标是稳健地最大化：

```text
expected net return
- risk penalty
- tail risk penalty
- turnover and impact
- concentration penalty
- uncertainty penalty
- operational risk penalty
```

不直接最大化回测 Sharpe。

## 11.3 预期收益稳健化

- 对预测做 shrinkage；
- 将模型不确定性转为折扣；
- 对极端 Alpha 截尾；
- 使用分状态历史校准；
- 对新模型设置更低权重上限；
- 预测优势接近成本时进入 no-trade zone。

## 11.4 风险估计

候选：

- EWMA；
- Ledoit-Wolf/OAS shrinkage；
- 因子协方差；
- 状态条件协方差；
- 稳健和尾部情景；
- bootstrap；
- 流动性调整风险。

协方差更新不得因为短期噪声造成剧烈杠杆变化。

## 11.5 约束

至少支持：

- gross/net exposure；
- 每资产/每合约上限；
- 每交易所上限；
- 每稳定币上限；
- 每策略和袖套风险预算；
- 杠杆、保证金和强平距离；
- 相关簇上限；
- 方向 Beta；
- 交易量参与率；
- 最小/最大订单；
- 换手；
- 未完成订单与多腿裸露；
- 可用余额和资产借贷；
- 风险状态下的更严格上限。

## 11.6 仓位规模

可使用：

- volatility scaling；
- risk budgeting；
- capped fractional Kelly 作为上限参考；
- CVaR/robust optimization；
- hierarchical allocation。

禁止全 Kelly。任何 Kelly 估计都必须折扣参数不确定性并有硬上限。

## 11.7 No-Trade Zone 与再平衡

只有当预期收益超过：

```text
fees + spread + impact + funding/borrow + uncertainty buffer + risk buffer
```

才交易。目标权重变化不足、流动性不足或执行成本异常时保持原仓位。

## 11.8 现金和避险资产

现金/稳定币是合法目标仓位，不要求始终满仓。稳定币本身也有发行人、链、交易所和脱锚风险，必须分开管理。

---

# 12. 回测、事件模拟和压力测试

## 12.1 双引擎原则

### 向量化引擎

用途：

- 快速筛选；
- 因子分析；
- 低频组合研究；
- 大范围消融。

### 事件驱动引擎

用途：

- 订单状态；
- 部分成交；
- 限价单；
- 多腿；
- 保证金；
- 资金费率；
- 延迟和故障；
- 账户与账本。

策略晋升必须通过事件驱动回放。两个引擎在可比场景下要有一致性测试，差异必须解释。

## 12.2 成本模型

必须包括：

- maker/taker fee；
- VIP 层级和历史费率；
- spread；
- price slippage；
- market impact；
- funding；
- borrow interest；
- 期权和交割合约结算费用；
- 转账和链上成本，在策略需要时；
- 多腿裸露；
- 取消/重挂机会成本；
- 推断和系统延迟。

成本参数有版本和来源。不能用一个固定 bps 覆盖所有市场。

## 12.3 成交模型层级

```text
Level 0: bar close/open 保守模型，仅用于粗筛
Level 1: trade/quote 驱动 spread 模型
Level 2: L2 depth sweep 和部分成交
Level 3: queue-aware 候选模型，只有数据足够时
```

没有订单队列位置数据时，不得假装精确知道限价单队列。使用区间或保守概率模型。

## 12.4 订单与延迟模拟

模拟：

- 信号计算延迟；
- 风险审查延迟；
- 网络往返；
- 交易所确认；
- WebSocket 延迟和乱序；
- REST 超时；
- 部分成交；
- cancel/replace race；
- 请求未知状态；
- 限频；
- 断线和恢复；
- 交易所维护；
- 本地进程重启。

## 12.5 保证金和强平

按交易所、产品和时间版本化：

- cross/isolated；
- initial/maintenance margin；
- leverage brackets；
- mark price；
- unrealized PnL；
- funding；
- liquidation/ADL 近似；
- 多仓、空仓和 hedge mode；
- 资产折扣和抵押品规则。

模拟不确定时使用更保守的假设，并明确标注精度等级。

## 12.6 多腿和跨所

必须模拟：

- 非原子成交；
- 第一腿成交、第二腿失败；
- 价格漂移；
- 资金分散；
- 转账不可即时；
- 交易所宕机；
- 稳定币/结算资产差异；
- 裸露名义和最长裸露时间。

## 12.7 历史规则和交易状态

回测必须使用当时：

- 合约规格；
- 最小金额和精度；
- 费率；
- 资金费率机制；
- 上下线；
- 维护和异常；
- 标记/指数规则，在可得时。

无法获得的历史规则要记录近似和风险，不得悄悄使用当前规则。

## 12.8 压力测试

至少包括：

- 成本 1.5x/2x/3x；
- 延迟 2x/5x；
- 流动性减半或更多；
- 相关性趋近 1；
- 稳定币脱锚；
- 交易所停止提现或交易；
- 瞬时跳空；
- 资金费率极端；
- 订单簿缺口；
- API 限频和断线；
- 模型不可用；
- 数据源滞后；
- 单策略失效；
- 历史重大事件回放。

## 12.8A 新闻、推文和事件回放

事件回放引擎必须与市场事件使用同一确定性时钟，并支持：

- 原始内容首次观察、修改、删除和互动快照；
- 网络/API 延迟、聚合延迟和队列延迟；
- X/Telegram/新闻断流与恢复；
- Claim/Event 状态转换；
- 官方确认、否认和转载扩散；
- 当时模型、翻译器、来源评分和事件本体；
- 事件模型推理耗时和费用；
- 事件到订单之间的完整决策延迟。

至少输出：

```text
signal_latency
source_latency
model_latency
market_move_before_signal
market_move_after_signal
corroboration_count_at_decision
revision_state_at_decision
engagement_snapshot_at_decision
```

历史内容不完整时，回测结果必须标记 `EVENT_DATA_INCOMPLETE`，不得与完整市场数据策略同等晋升。

## 12.9 回测指标

### 收益与风险

- CAGR/年化收益；
- volatility；
- Sharpe/Sortino/Calmar；
- max drawdown；
- expected shortfall；
- skew/kurtosis；
- underwater duration；
- tail loss；
- hit rate 与 payoff ratio。

### 交易与执行

- turnover；
- maker/taker 比例；
- fill rate；
- slippage；
- adverse selection；
- participation rate；
- cancel rate；
- latency；
- multi-leg exposure。

### 稳健性

- walk-forward fold distribution；
- PBO；
- DSR/PSR；
- parameter stability；
- regime contribution；
- asset/venue contribution；
- bootstrap confidence intervals；
- cost break-even；
- capacity curve。

## 12.10 结果工件

每个回测必须输出：

```text
run_manifest.json
orders.parquet
fills.parquet
ledger_entries.parquet
positions.parquet
equity_curve.parquet
pnl_attribution.parquet
metrics.json
validation_report.md
cost_report.md
risk_report.md
reproduction_command.txt
```


---

# 13. 权威会计、PnL 与账户对账

## 13.1 双重记账是交易系统核心

所有资金、成交、手续费、资金费率、借贷、划转和调整都进入不可变账本。页面、策略和模型只能读取账本投影，不能各自计算一个不同版本的“账户收益”。

## 13.2 账户科目建议

```text
Assets
├── Cash:<venue>:<asset>
├── MarginCollateral:<venue>:<asset>
├── PositionCost:<venue>:<instrument>
├── Receivable
└── InTransit

Liabilities
├── BorrowedAsset:<venue>:<asset>
├── AccruedInterest
└── Payable

Equity
├── OwnerCapital
├── RetainedPnL
└── ReconciliationReserve

Income
├── TradingRealizedPnL
├── FundingIncome
├── InterestIncome
└── OtherIncome

Expenses
├── TradingFee
├── FundingExpense
├── BorrowInterest
├── SlippageAttribution
├── TransferFee
└── OtherExpense
```

科目和分录模板必须版本化。不同产品的经济处理由单元测试覆盖。

## 13.3 成交入账

每个 Fill 至少生成：

- 资产/头寸变化；
- 现金或保证金变化；
- 手续费；
- 成本基础/lot；
- 已实现 PnL，在关闭或减少仓位时；
- 与订单、策略、账户和交易所的引用。

分录总借方必须等于总贷方。任何不平衡是致命错误。

## 13.4 已实现与未实现 PnL

- 已实现 PnL 只能来自成交和确定现金流。
- 未实现 PnL 是按版本化估值价格生成的投影，不直接写入永久收益科目。
- 估值价格优先级和异常回退必须配置：mark、mid、last、index 等不得混用。
- 正向/逆向合约使用各自正确公式。
- 资金费率和借贷利息单独归因。
- 交易费不得隐藏在成交价格中而丢失明细。

## 13.5 PnL 分解

权威分解：

```text
Ending Equity - Starting Equity - Net External Transfers
=
Realized Trading PnL
+ Unrealized PnL Change
+ Funding Income/Expense
+ Borrow Interest
- Trading Fees
- Transfer/Settlement Fees
+ Reconciliation Adjustments
```

页面还应按以下维度分解：

- 策略；
- 袖套；
- 币种/合约；
- 交易所；
- 方向；
- 模型；
- 市场状态；
- alpha、beta、carry、execution、cost。

归因分配规则必须守恒：子项之和等于权威总额，舍入差有专门科目。

## 13.6 对账层级

### 启动对账

进程启动时：

1. 禁止新订单；
2. 读取本地未终结订单；
3. 获取交易所 open orders、recent orders、fills、balances、positions；
4. 比较并生成差异；
5. 恢复缺失更新；
6. 不能解释的差异进入 `HALTED` 或 `REDUCE_ONLY`；
7. 验收后才允许继续。

### 持续对账

- 用户数据流事件驱动；
- REST 定时确认；
- 订单、成交、仓位、余额、资金费率和费率逐层比较；
- 断线重连后强制完整或时间窗对账；
- 每日生成签名快照。

## 13.7 差异处理

差异分类：

```text
EXPECTED_TIMING
MISSING_LOCAL_EVENT
MISSING_VENUE_EVENT
DUPLICATE_EVENT
ROUNDING
FEE_MISMATCH
POSITION_MISMATCH
BALANCE_MISMATCH
UNKNOWN_ORDER
UNEXPLAINED
```

禁止静默修改余额以“对上”。任何调整必须有 `ReconciliationAdjustment`、原因、证据和审批。

## 13.8 账本测试

必须包括：

- 买入/卖出；
- 加仓/减仓/反手；
- 多次部分成交；
- 正向/逆向永续；
- 手续费由不同资产支付；
- 资金费率正负；
- 借贷和利息；
- 交割合约结算；
- 期权权利金和到期，后续；
- 交易撤销/更正事件；
- 重复消息幂等；
- 进程崩溃恢复；
- 舍入和最小单位。

使用属性测试验证借贷平衡、资产守恒和重放幂等。

---

# 14. 独立风险引擎

## 14.1 独立性

风险引擎是交易前最后一道不可绕过的确定性服务：

- 不由策略包提供；
- 不由模型或 LLM 修改；
- 使用独立版本化政策；
- 能在信号服务失控时拒绝全部新风险；
- 能在执行服务失控时触发停机；
- 风险配置发布需要人工审批。

## 14.2 风险状态

```text
NORMAL
CAUTION
REDUCE_ONLY
HALTED
RECOVERY
```

含义：

- `NORMAL`：允许符合政策的新开仓。
- `CAUTION`：降低限额、提高门槛、禁止高风险袖套。
- `REDUCE_ONLY`：只能减少经济风险，不新增。
- `HALTED`：停止新命令，按政策撤单和处置。
- `RECOVERY`：完成对账和人工检查，仍不允许恢复全部风险。

状态转移必须记录原因和操作者；自动只能向更安全状态迁移，不能自动从 `HALTED` 回到 `NORMAL`。

## 14.3 风险快照

每次审查使用一致的 `RiskSnapshot`：

- 账本权益；
- 余额与仓位；
- open orders；
- 未完成多腿裸露；
- mark/index/mid 价格和新鲜度；
- 保证金和强平距离；
- 交易所、稳定币、链和资产集中度；
- 策略和因子暴露；
- 相关性和尾部场景；
- 当日损益、滚动回撤；
- 数据、模型和系统健康。

风险数据过旧时拒绝新开仓。

## 14.4 预交易限制

至少支持：

### 订单级

- 最大名义金额；
- 最大数量；
- 价格偏离；
- fat-finger；
- 最小金额和精度；
- post-only/IOC/FOK 合法性；
- 预计滑点；
- 订单寿命；
- 重复意图。

### 资产/合约级

- 最大净/总暴露；
- 杠杆；
- 流动性和参与率；
- 当日交易额；
- 下线/维护/异常状态；
- 集中和相关簇。

### 策略级

- 风险预算；
- 最大回撤；
- 日内亏损；
- 换手；
- 模型置信度；
- 只允许已批准版本。

### 账户/交易所级

- gross/net exposure；
- 保证金利用；
- 距强平缓冲；
- 交易所集中；
- stablecoin 集中；
- API/账户健康；
- 可用现金；
- open order 数量和限频。

## 14.5 事中与事后风险

持续监控：

- 实际 vs 目标仓位；
- 成交滑点；
- 多腿裸露；
- 订单拒绝和未知状态；
- PnL 和 drawdown；
- margin ratio；
- 风险模型漂移；
- 数据/模型新鲜度；
- 交易所异常；
- 账户对账差异。

风险事件必须写入 Incident 系统和仪表盘。

## 14.6 熔断器

```text
DATA_STALE
DATA_CORRUPT
CLOCK_DRIFT
MODEL_DRIFT
MODEL_UNAVAILABLE
ENSEMBLE_DISAGREEMENT
LOSS_LIMIT
DRAWDOWN_LIMIT
MARGIN_LIMIT
LIQUIDITY_COLLAPSE
VENUE_DISCONNECTED
VENUE_MAINTENANCE
ORDER_REJECTION_SPIKE
UNKNOWN_ORDER_STATE
RECONCILIATION_FAILURE
LEDGER_IMBALANCE
SECRET_OR_SECURITY_EVENT
MANUAL_KILL
```

每个熔断器定义：触发条件、去抖、状态迁移、允许动作、告警、恢复前置条件和测试。

## 14.7 紧急动作顺序

默认：

```text
阻止新风险
→ 阻止新非减仓订单
→ 撤销非必要挂单
→ 对账
→ 评估当前裸露与流动性
→ 按已批准政策减仓/对冲
→ 进入 HALTED
```

“立即市价平掉所有仓位”不是通用默认，因为可能在流动性崩溃中放大损失。不同事故类型需要预先定义处置剧本。

## 14.8 风险政策版本示例

```yaml
policy_id: "personal_default_v1"
mode: "paper"
limits:
  account:
    max_gross_leverage: "1.0"
    max_daily_loss_fraction: "0.01"
    max_rolling_drawdown_fraction: "0.05"
  venue:
    max_equity_fraction: "0.50"
  stablecoin:
    max_equity_fraction: "0.60"
  instrument:
    max_equity_fraction: "0.10"
  order:
    max_equity_fraction: "0.01"
    max_expected_slippage_bps: "20"
health:
  max_market_data_age_ms: 2000
  max_account_data_age_ms: 5000
recovery:
  manual_approval_required: true
```

这些数值只是 Paper 阶段的示例结构，不得自动作为用户真实风险偏好。`P00` 生成风险问卷和待确认配置；在用户未确认前只允许零资金 Paper。

## 14.9 Live 解锁

实盘解锁必须同时满足：

- 运行模式和发布包明确为 Canary；
- Paper/Shadow/Testnet 验收全部通过；
- 风险政策已人工确认；
- 使用专用低余额子账户；
- API 无提现；
- IP 白名单和权限最小化；
- 账户、主机和配置指纹匹配；
- 解锁文件签名、单次、可过期；
- 启动前对账通过；
- 监控和告警有效；
- 一键停机测试通过。

解锁到期或任何指纹变化都回到锁定状态。

---

# 15. 交易执行系统

## 15.1 执行服务职责

执行服务只接收已批准且未过期的 `OrderIntent`。它负责：

- 交易所规则量化；
- 订单拆分和算法选择；
- client order ID；
- 幂等提交；
- 状态机；
- WebSocket/REST 更新；
- 部分成交；
- 撤单/改单；
- 多腿风险；
- 错误恢复；
- 发送 Fill 到账本；
- 持续对账。

它不能重新决定策略方向，也不能放大风险批准的目标。

## 15.2 Execution Adapter 协议

```python
class ExecutionVenueAdapter(Protocol):
    async def instruments(self) -> list[Instrument]: ...
    async def account_snapshot(self) -> AccountSnapshot: ...
    async def open_orders(self) -> list[VenueOrder]: ...
    async def recent_orders(self, since: datetime) -> list[VenueOrder]: ...
    async def recent_fills(self, since: datetime) -> list[VenueFill]: ...
    async def submit(self, command: SubmitOrderCommand) -> SubmitResult: ...
    async def cancel(self, command: CancelOrderCommand) -> CancelResult: ...
    async def amend(self, command: AmendOrderCommand) -> AmendResult: ...
    async def stream_account(self) -> AsyncIterator[AccountEvent]: ...
    async def health(self) -> VenueHealth: ...
```

任何 Adapter 必须通过官方沙盒/Testnet 契约测试和录制回放测试。

## 15.3 订单状态机

内部状态至少包括：

```text
CREATED
RISK_APPROVED
SUBMITTING
SUBMIT_UNKNOWN
VENUE_ACCEPTED
PARTIALLY_FILLED
FILLED
CANCEL_REQUESTED
CANCEL_UNKNOWN
CANCELED
REJECTED
EXPIRED
RECOVERY_REQUIRED
TERMINAL_RECONCILED
```

状态转移必须单调、可重放、幂等。交易所状态映射和内部状态分开。

### 关键规则

- 请求超时不等于失败；进入 `SUBMIT_UNKNOWN`。
- 在未知状态确认前禁止使用相同经济意图盲目重发。
- 部分成交后目标变化需重新经过风险审查或使用预批准剩余逻辑。
- Terminal 状态仍需最终对账。
- 迟到或乱序事件不能使状态回退。

## 15.4 Client Order ID 与幂等

Client Order ID 必须编码或关联：

- 策略/发布 ID；
- OrderIntent ID；
- 切片序号；
- 重试代次；
- 校验字符；
- 不含秘密和敏感信息。

相同幂等键只对应一个经济订单。重试必须先查询已有订单。

## 15.5 WebSocket 与 REST 双路径

- 用户数据 WebSocket 是低延迟更新路径。
- REST 是启动、断线、超时和周期性对账路径。
- WebSocket 断线必须检测 sequence/时间缺口。
- 重连后从 REST 或官方恢复方法重建状态。
- 不依赖浏览器或前端保持连接。

## 15.6 动态交易规则

下单前读取缓存的官方 instrument snapshot，并验证新鲜度：

- price tick；
- quantity step；
- min/max quantity；
- min notional；
- order type；
- position mode；
- leverage/margin；
- trading status；
- price protection；
- self-trade prevention；
- rate limit。

规则不能写死在策略代码中。

## 15.7 执行算法

首批：

- Market with protection；
- Aggressive limit；
- Passive post-only；
- Time-bounded passive；
- TWAP；
- participation/VWAP 候选；
- Reduce-only emergency；
- 多腿顺序和对冲。

算法选择基于：

- signal half-life；
- spread/depth；
- expected impact；
- fill probability；
- adverse selection；
- urgency；
- 风险裸露；
- 交易所状态。

## 15.8 Maker/Taker 选择

不是固定偏好 maker。比较：

```text
maker rebate/fee
+ fill probability
- adverse selection
- timeout opportunity cost
- reprice/cancel cost
vs
taker fee
+ immediate spread/impact
+ reduced exposure risk
```

执行模型必须通过实际 Paper/Testnet/Canary 成交持续校准。

## 15.9 多腿交易

定义 `ExecutionGroup`：

- 所有腿；
- 目标 delta；
- 最大裸露名义；
- 最大裸露时间；
- 优先腿；
- 对冲腿；
- 部分成交规则；
- 失败处置；
- 允许的紧急 unwind。

每个状态变化重新评估裸露和保证金。不能假定跨交易所原子成交。

## 15.10 限频和背压

- 从官方响应动态更新配额；
- 高优先级保留给撤单、对账和风险动作；
- 市场数据、研究和交易请求隔离预算；
- 指数退避带随机抖动，但订单未知状态不做普通重试；
- 队列过载时丢弃低优先级行情更新而不是延迟风险命令；
- 记录每类请求延迟和拒绝。

## 15.11 启动、关闭和崩溃恢复

### 启动

```text
加载并验证配置
→ 检查实盘锁
→ 时间同步
→ 数据和账户连接
→ 读取本地事件/订单/账本
→ REST 全面对账
→ 检查风险状态
→ 启动账户流
→ 进入允许模式
```

### 优雅关闭

- 停止新意图；
- 按政策处理挂单；
- 刷新事件和账本；
- 保存快照；
- 写入关闭原因；
- 不擅自平仓，除非政策明确。

### 崩溃恢复

事件日志和数据库事务必须保证：

- 命令和 outbox 原子；
- Fill 和账本分录幂等；
- 重放不重复交易；
- 未知状态进入恢复队列；
- 无法恢复时自动 `HALTED`。

## 15.12 交易所故障和 Changelog Watcher

自动监控：

- 官方变更日志；
- API schema 差异；
- 枚举新增；
- 限频和权重；
- 维护公告；
- 测试请求行为；
- 证书和 DNS；
- Adapter 版本。

发现破坏性变化时：

```text
创建 Incident
→ 禁止受影响路径的新风险
→ 运行契约测试
→ 生成升级 ADR
→ Paper/Testnet 回归
→ 人工批准后发布
```

## 15.13 执行安全测试

必须覆盖：

- 超时但已成交；
- 超时且未成交；
- 重复提交；
- 迟到事件；
- 部分成交后断线；
- 撤单与成交竞态；
- 重启后未知订单；
- API 限频；
- 交易所返回新增状态；
- 精度规则变化；
- 账户模式不匹配；
- 多腿第二腿失败；
- 账本写入失败；
- 数据陈旧；
- 人工 Kill Switch。

---

# 16. 策略、模型和系统晋升流程

## 16.1 晋升状态

```text
IDEA
STRUCTURED
REPRODUCED
RESEARCH_CANDIDATE
OOS_QUALIFIED
REPLAY_QUALIFIED
PAPER
SHADOW
TESTNET
CANARY
LIMITED_LIVE
SUSPENDED
RETIRED
```

每次状态迁移都需要证据包和批准者。

## 16.2 `IDEA → STRUCTURED`

要求：

- Hypothesis Spec；
- 经济机制；
- 数据需求；
- 证伪条件；
- 来源谱系；
- 初步偏差检查。

## 16.3 `STRUCTURED → REPRODUCED`

外部来源策略需：

- 在统一数据上从零实现；
- 复现方向或解释差异；
- 使用统一成本；
- 记录缺失信息；
- 通过静态和泄漏审计。

自研策略可跳过“原文复现”，但仍需基线复现和测试。

## 16.4 `RESEARCH_CANDIDATE → OOS_QUALIFIED`

要求：

- 完整实验账本；
- walk-forward、purge/embargo；
- 多重试验修正；
- 成本/参数/状态压力；
- 最终 holdout；
- 模型卡、策略卡和风险卡；
- 与现有组合的增量分析。

## 16.5 `OOS_QUALIFIED → REPLAY_QUALIFIED`

通过事件回放：

- 真实合约规则；
- 成交和费用；
- 部分成交；
- 资金费率；
- 保证金；
- 断线和延迟；
- 账本和对账；
- 故障注入。

## 16.6 `REPLAY_QUALIFIED → PAPER`

Paper 使用实时行情和完整决策/风险/执行/账本路径，但不发送交易所订单。必须保留虚拟成交模型和预测误差。

## 16.7 `PAPER → SHADOW`

Shadow 与真实账户状态并行运行，但仅记录“本来会下什么单”。比较：

- 预期 vs 可成交价格；
- 订单拒绝；
- 限频；
- 数据延迟；
- 风险决策；
- 实际市场容量。

## 16.8 `SHADOW → TESTNET`

Testnet 验证 API、状态机和恢复，不将 Testnet 价格/流动性当作实盘策略证据。

## 16.9 `TESTNET → CANARY`

Canary 条件：

- 专用低余额账户；
- 极低名义；
- 低杠杆或无杠杆；
- 有限币种和单一策略；
- 短期可撤销；
- 24/7 告警；
- 人工在线；
- 自动风险削减和锁定；
- 预先定义停止条件。

## 16.10 `CANARY → LIMITED_LIVE`

只按预先定义的阶梯扩大。每次扩大视为新实验，必须观察足够成交和风险事件。任何回撤、滑点、对账、漂移或基础设施异常触发回退。

## 16.11 降级与退休

触发：

- 校准恶化；
- 真实成本超过 break-even；
- 状态外行为；
- 风险预算消耗；
- 数据源失效；
- 交易所规则变化；
- 与其他策略高度重复；
- 事故；
- 许可证变化。

模型和策略可以回到 Paper、Suspended 或 Retired，不能因历史好看永久保留。


---

# 17. 网页版量化看板：产品、视觉、数据与交互总规格

## 17.1 产品定位

主看板是 AegisQuant 的**运营与研究工作台**，用于查看历史、当日、实时和故障状态，不是网页交易终端。它必须做到：

- 5 秒内判断系统是否安全、是否盈利、风险是否异常；
- 从总账户下钻到策略、模型、信号、订单、成交和账本；
- 清楚区分实际、预测、模拟和估计；
- 明确显示数据新鲜度和可信度；
- 支持研究、交易和基础设施的统一时间轴；
- 保持克制、专业、高信息密度和可读性。

设计参考应研究：OpenBB Workspace 的可组合金融工作区、Hummingbot Dashboard 的账户/机器人视图、FreqUI 的策略运行管理、TradingView 的图表交互、Bloomberg 类高密度信息结构、Grafana 的可观测性模式。只吸收交互原则，不复制品牌、代码或受版权保护视觉资产。

## 17.2 三层界面

```text
业务看板：Next.js 主产品界面
运维看板：Grafana 指标、日志、追踪和告警
紧急控制：独立、最小化、强认证的运维入口
```

主业务看板不直接查询交易数据库，不直接访问交易所，不保存 API 密钥。

## 17.3 信息架构

```text
/overview
/live
/performance
/execution
/strategies
/models
/market
/intelligence
/risk
/research
/research/intelligence
/data
/incidents
/system
/settings
```

全局导航包含：

- 环境：Research / Paper / Shadow / Testnet / Canary / Live；
- 账户；
- 时间范围；
- 时区；
- 币种/策略/交易所筛选；
- 数据新鲜度；
- 风险状态；
- 最后权威对账时间；
- 全局命令面板；
- 告警中心。

## 17.4 视觉方向

关键词：

```text
专业
冷静
高密度
有层次
少装饰
强对齐
数据优先
风险醒目但不过度闪烁
```

禁止：

- 赌场化视觉；
- 夸张霓虹、过量渐变或动态背景；
- 3D 饼图；
- 无意义玻璃拟态；
- 红绿作为唯一编码；
- 依赖动画表达关键状态；
- 在页面中堆满无法比较的 KPI 卡片。

## 17.5 Design Tokens

建立语义 Token，不在组件中散落颜色：

```text
surface.canvas
surface.panel
surface.elevated
border.subtle
border.strong
text.primary
text.secondary
text.muted
accent.primary
status.positive
status.negative
status.warning
status.critical
status.info
status.stale
chart.grid
chart.crosshair
```

提供：

- 深色和浅色主题；
- 紧凑/舒适密度；
- 中国习惯“红涨绿跌”和国际习惯“绿涨红跌”切换；
- 色盲安全模式；
- 高对比模式；
- 等宽数字和 tabular numerals；
- 中文、英文及数字混排字体栈使用系统字体，不分发字体文件。

推荐布局：

- 12 列桌面栅格；
- 8px spacing scale；
- 页面最大宽度根据数据密度可全宽；
- KPI 行高和表格行高可切换；
- 面板圆角适中、阴影克制；
- 主要分隔依赖留白、边框和排版，而不是大量卡片嵌套。

## 17.6 全局状态语义

每个实时组件必须有：

```text
LOADING
EMPTY
LIVE
STALE
DEGRADED
DISCONNECTED
ERROR
PERMISSION_DENIED
```

必须显示：

- 数据截至时间；
- 延迟；
- 来源；
- 是否权威；
- 是否估算；
- 最近成功刷新；
- 错误和降级原因。

旧数据不能继续显示为“实时”而无提示。

## 17.7 通用组件

建立 Storybook 组件库：

- `MetricTile`；
- `MetricDelta`；
- `StatusBadge`；
- `FreshnessIndicator`；
- `RiskStateBanner`；
- `EnvironmentBadge`；
- `EquityChart`；
- `DrawdownChart`；
- `CandlestickTradeChart`；
- `AttributionWaterfall`；
- `PnLHeatmap`；
- `ExposureTreemap`；
- `CorrelationMatrix`；
- `OrderTimeline`；
- `SignalDecisionTrace`；
- `DataQualityGrid`；
- `ModelCalibrationChart`；
- `IncidentTimeline`；
- `VirtualDataTable`；
- `FilterBar`；
- `CommandPalette`；
- `EmptyState`；
- `ErrorBoundaryPanel`；
- `ExportMenu`。

每个组件必须有正常、加载、空、陈旧、错误、窄屏和无障碍 Story。

## 17.8 `/overview`：Command Center

首屏目标：立即回答“系统现在安全吗、今天发生了什么”。

### 顶部状态带

- 环境和账户；
- 风险状态；
- Live lock 状态；
- 数据/账户流状态；
- 最后对账；
- 未确认严重告警；
- 系统时钟偏差。

### 核心 KPI

- 权威权益；
- 当日净 PnL；
- 已实现/未实现；
- 费用；
- 资金费率；
- gross/net exposure；
- 杠杆和保证金利用；
- 当前 drawdown；
- 风险预算使用；
- active strategies/models；
- open/unknown orders。

### 主图

- 权益曲线 + 当日细节；
- 回撤；
- PnL 来源分解；
- 策略贡献；
- 资产和交易所暴露；
- 最近信号与成交时间轴；
- 当前重大风险和事故。

所有 KPI 可点击下钻；卡片不能只是静态数字。

## 17.9 `/live`：当日与实时量化

内容：

- 实时权益、现金、仓位和保证金；
- 分钟级当日 PnL；
- realized/unrealized/funding/fees/slippage；
- 当前目标 vs 实际暴露；
- 活跃策略和信号；
- 风险审查结果；
- open orders、partial fills、unknown orders；
- 数据和模型新鲜度；
- 市场状态；
- 关键行情卡片。

提供“时间回放光标”，可查看某一时点系统当时知道什么，不能用当前修订数据覆盖历史视角。

## 17.10 `/performance`：历史业绩与归因

### 时间选择

```text
1D / 7D / 30D / MTD / QTD / YTD / 1Y / ALL / Custom
```

### 图表

- 权益与基准；
- 回撤和恢复；
- 日/周/月收益热力图；
- rolling Sharpe/volatility/beta；
- 收益分布和 QQ；
- 尾部与 worst periods；
- underwater duration；
- 策略、资产、交易所、方向和状态归因；
- gross-to-net waterfall；
- turnover、cost 和 capacity；
- live vs backtest/Paper 差异。

### 指标说明

每个指标提供公式、频率、数据截至时间和是否年化。禁止用模糊“胜率”“收益率”而不说明口径。

## 17.11 `/execution`：订单、成交与执行质量

### 总览

- submitted/accepted/rejected/unknown；
- fill rate；
- maker/taker；
- average/slippage distribution；
- adverse selection；
- latency 分位数；
- cancel/replace；
- 多腿裸露；
- 交易所和策略分解。

### 订单表

列至少包括：

```text
时间
环境
策略
信号
RiskDecision
交易所/合约
方向
类型
价格/数量
已成交
状态
client/venue ID
预期/实际滑点
费用
延迟
错误码
```

### 订单详情

展示完整链路：

```text
Feature Snapshot
→ Forecast
→ Signal
→ Portfolio Proposal
→ Risk Decision
→ Order Intent
→ Commands
→ Venue Updates
→ Fills
→ Ledger Entries
→ Reconciliation
```

### K 线与成交回放

使用 Lightweight Charts：

- K 线/中间价；
- 信号；
- 目标仓位；
- 订单提交、撤单和成交；
- 风险事件；
- 资金费率；
- 跨所价差，可选。

## 17.12 `/strategies`：策略中心

列表显示：

- 状态和版本；
- 袖套；
- 环境；
- 分配资本/风险；
- 当日/历史净 PnL；
- 回撤；
- OOS/Live 指标；
- 换手和成本；
- 当前信号；
- 数据/模型依赖；
- 最近发布和失效时间。

详情页：

- Strategy Spec；
- 经济假设；
- 参数来源；
- 验证报告；
- 状态分段；
- 相关/重复策略；
- 模型依赖；
- 交易和 PnL；
- 已知失效模式；
- 晋升历史；
- 版本差异。

不允许前端直接编辑实盘参数。研究配置变更产生提案和审计记录。

## 17.13 `/models`：AI 和预测中心

列表：

- 模型家族和版本；
- 目标和 horizon；
- 状态；
- 数据集/特征；
- OOS 指标；
- live calibration；
- 推断延迟；
- drift/OOD；
- 资源使用；
- 所属策略。

详情：

- Model Card；
- 训练谱系；
- 预测分布；
- calibration/reliability diagram；
- confusion/quantile coverage；
- feature importance/SHAP，仅解释关联；
- ensemble weight；
- disagreement；
- abstain 统计；
- 状态和资产切片；
- shadow/live 差异；
- 漂移事件和降级历史。

明确标注基础模型、简单基线和当前 Champion/Challenger。

## 17.14 `/market`：市场情报

内容：

- 现货、永续、期货和期权概览；
- 资金费率矩阵；
- 基差和期限结构；
- OI 与强平；
- 波动率和相关性状态；
- 流动性/盘口；
- 跨交易所价格差；
- 链上和宏观候选特征；
- 官方公告和事件；
- 数据来源与延迟。

市场页是研究和上下文，不直接给出“买入建议”。

## 17.14A `/intelligence`：全球事件与社交情报中心

该页面是第一等业务页面，不是新闻链接列表。必须包含：

### Event Radar

- 正在形成、已确认、被否认和已解决事件；
- 影响资产、事件类型、首次观察、当前状态和置信度；
- `5m/30m/4h/1d/7d` 影响分布；
- 价格是否已先行；
- 风险动作和策略是否 abstain；
- 数据质量和来源许可状态。

### Evidence Graph

- 原始内容、Claim、支持、反驳、转载和官方确认关系；
- 独立来源家族，而非简单文章数量；
- 每个 AI 结论可点回证据片段、原文链接、模型和时间；
- 权限不允许全文展示时仅显示合法摘要、ID 和重新获取入口。

### Narrative Monitor

- X/Telegram/Bluesky/新闻的主题速度和跨平台扩散；
- 可信度加权 stance；
- 叙事拥挤、机器人/协调传播风险；
- 与价格、成交、OI、资金费率、基差和链上流的同步图；
- attention half-life 和历史相似事件。

### Source Monitor

- 官方账号和关键来源 allowlist；
- Provider 延迟、额度、断流、删除同步和政策状态；
- 来源领域历史准确性、修正率和首次报道速度；
- 身份或行为异常，不展示对普通用户的敏感画像。

### Event Replay

- 在统一时间轴上重放：消息首次出现 → 多源确认 → 市场反应 → 信号 → 风控 → 订单/不交易；
- 支持“当时系统知道什么”的 point-in-time 视图；
- 禁止默认显示最终事实或最终互动数。

### Alert Inbox

- `INFO / WATCH / CAUTION / REDUCE / HALT`；
- 每个告警有证据、阈值、自动动作、人工确认和关闭条件；
- 允许用户标记误报、补充来源和提交标注，但不能在页面中绕过风险策略。

## 17.15 `/risk`：风险中心

顶部固定显示风险状态。内容：

- 账户、策略、资产、交易所和稳定币限额；
- 当前值、上限、余量和趋势；
- gross/net/leverage；
- margin 和 liquidation buffer；
- VaR/ES 和压力场景；
- 相关性和集中度；
- drawdown 和日内损失；
- 多腿裸露；
- 数据/模型/执行风险；
- 事件情报断流、来源政策、内容删除同步和高影响事件风险；
- 熔断器状态；
- 风险决策拒绝原因；
- 事故剧本和最近演练。

风险指标必须能回到权威账本和快照。

## 17.16 `/research`：实验与研究

- Hypothesis 队列；
- Run 排行榜；
- 所有失败试验；
- 数据集和 split；
- Model Council 比较；
- walk-forward；
- PBO/DSR；
- 参数稳定性；
- 成本压力；
- 状态切片；
- Champion/Challenger；
- 研究资源使用；
- 复现命令和工件。

默认排序不能只按最高 Sharpe；提供稳健性综合评分，并显示总试验次数。

## 17.17 `/research/intelligence`：知识与策略情报

包含聚宽但不局限于聚宽：

- 来源目录；
- 权限和许可；
- 原始工件和证据；
- 静态分析；
- Strategy IR；
- 审计标签；
- Alpha 原语；
- 重复簇；
- 加密迁移队列；
- 复现状态；
- 与现有策略/R331 的比较；
- 失败分类。

浏览外部正文时使用安全渲染，不执行脚本、宏或 Notebook。

## 17.18 `/data`：数据目录与质量

- Provider Registry；
- 订阅/权限和额度；
- 数据集目录；
- 时间覆盖；
- 缺口、重复和异常；
- 新鲜度；
- schema 变化；
- point-in-time 状态；
- 来源交叉核验；
- lineage；
- 存储使用；
- paid-source bakeoff；
- quarantine。

提供 instrument/date/provider 下钻和质量报告导出。

## 17.19 `/incidents`：告警和事故

- Open/Acknowledged/Mitigated/Resolved；
- severity；
- 首次/最后发生；
- 影响账户/策略/数据源；
- 时间轴；
- 相关日志、指标、订单、对账和配置；
- 执行的自动动作；
- 人工确认；
- postmortem；
- 重复事故关联。

确认告警是允许的受审计写操作，但不能因此自动恢复风险状态。

## 17.20 `/system`：系统运行

- 服务和进程；
- 版本/commit；
- CPU/GPU/RAM/磁盘；
- 队列和任务；
- API/WS 延迟；
- 数据库；
- 对象存储；
- 时间同步；
- 备份；
- 依赖和交易所 changelog；
- 最近部署；
- 健康检查。

链接到 Grafana，但主页面提供业务可读摘要。

## 17.21 `/settings`：设置与权限

首版允许：

- 主题和密度；
- 时区；
- 红绿习惯；
- 数值显示；
- 页面布局；
- 告警渠道和静默时间，需审计；
- 数据导出；
- 会话安全；
- 只读 Provider 状态。

不允许：

- 输入交易所密钥；
- 任意下单；
- 在线修改 Live 风险上限；
- 直接发布模型或策略；
- 解锁 Live。

## 17.22 Read Model

为什么需要 Read Model：

- 防止前端查询交易核心库；
- 固化口径；
- 提升性能；
- 允许重建；
- 隔离敏感字段；
- 支持历史快照和实时增量。

建议投影：

```text
rm_account_overview
rm_account_timeseries
rm_daily_pnl
rm_pnl_attribution
rm_positions_current
rm_exposures
rm_risk_limits
rm_risk_events
rm_strategies
rm_strategy_timeseries
rm_models
rm_model_metrics
rm_signals
rm_orders
rm_fills
rm_execution_quality
rm_market_state
rm_event_clusters
rm_event_claims
rm_event_impact_forecasts
rm_narrative_states
rm_source_identities
rm_source_policy_status
rm_social_attention_snapshots
rm_data_health
rm_provider_health
rm_incidents
rm_system_health
rm_reconciliation_status
rm_research_runs
rm_intelligence_sources
```

Read Model 必须包含 `as_of_time`、`projected_at`、`source_watermark` 和 `quality_state`。

## 17.23 REST API

统一前缀：

```text
/api/v1
```

示例：

```text
GET /overview
GET /accounts
GET /accounts/{id}/equity
GET /accounts/{id}/pnl
GET /positions
GET /exposures
GET /risk/summary
GET /risk/limits
GET /risk/events
GET /strategies
GET /strategies/{id}
GET /models
GET /models/{id}
GET /signals
GET /orders
GET /orders/{id}/trace
GET /fills
GET /execution/quality
GET /market/funding
GET /market/basis
GET /market/state
GET /intelligence/events
GET /intelligence/events/{id}
GET /intelligence/events/{id}/evidence
GET /intelligence/narratives
GET /intelligence/sources
GET /intelligence/alerts
GET /intelligence/replay/{id}
GET /research/runs
GET /research/runs/{id}
GET /intelligence/sources
GET /data/providers
GET /data/quality
GET /incidents
GET /system/health
POST /incidents/{id}/acknowledge
POST /research/jobs/{id}/cancel
```

允许的 POST 都必须审计和幂等。所有筛选、分页、排序和时区语义写入 OpenAPI。

## 17.24 WebSocket / 实时事件

```text
/ws/v1/stream
```

订阅主题：

```text
account.summary
pnl.live
positions.live
risk.state
orders.live
fills.live
signals.live
intelligence.events
intelligence.narratives
intelligence.alerts
intelligence.sources
data.health
incidents.live
system.health
```

消息至少包含：

```json
{
  "schema_version": "1",
  "topic": "risk.state",
  "event_id": "...",
  "event_time": "...",
  "server_time": "...",
  "sequence": 0,
  "payload": {}
}
```

要求：

- 心跳；
- sequence gap 检测；
- 重连退避；
- 重连后 REST snapshot + 增量；
- 每个客户端订阅限额；
- 背压；
- 敏感字段过滤；
- 不保证 WS 是权威持久事实。

## 17.25 查询和下采样预算

- 大于屏幕像素数的时序必须服务端下采样；
- 保留 first/last/min/max 和重要事件；
- K 线使用多粒度预聚合；
- 表格游标分页和虚拟化；
- 单次导出有行数和时间范围限制；
- 慢查询记录和告警；
- 页面不能在浏览器中加载完整多年 tick 数据。

## 17.26 性能 SLO

本地/私网目标：

- Overview 首屏 p75 < 1.5 秒；
- 常用缓存 API p95 < 300 ms；
- 聚合历史 API p95 < 1 秒；
- 实时关键事件端到端 p95 < 1 秒；
- 页面交互 60fps 目标；
- 10 万行逻辑表格通过虚拟化可操作；
- 长任务异步并显示进度，不能阻塞 API。

所有目标用自动基准验证，不以主观感受验收。

## 17.27 可访问性与本地化

必须达到 WCAG 2.2 AA 的合理范围：

- 键盘导航；
- 焦点可见；
- 语义 HTML；
- 图表有文字摘要和数据表替代；
- 颜色不是唯一状态；
- 对比度；
- 减少动画；
- 屏幕阅读器标签；
- 数字、日期、币种和时区明确。

中文为默认，文案不得混用难懂缩写；专业术语提供 tooltip。

## 17.28 鉴权与网络

默认：

- Web/API 绑定 localhost 或私网；
- 远程访问优先 Tailscale/WireGuard；
- TLS；
- 使用成熟 OIDC/反向代理认证或 Passkey，不自行设计密码学；
- HttpOnly、Secure、SameSite Cookie；
- CSRF 防护；
- 严格 CSP；
- session 过期和撤销；
- 审计登录、失败和权限变化。

角色：

```text
VIEWER
OPERATOR
ADMIN
```

单用户也保留角色模型，便于最小权限。网页服务账号只能读取 Read Model 和有限控制表。

## 17.29 前端测试

- 组件单元测试；
- Storybook 交互和可访问性；
- API schema 生成和类型检查；
- 视觉回归；
- Playwright E2E；
- WebSocket 断线/乱序；
- 大数据性能；
- 时区和红绿切换；
- 空/陈旧/错误状态；
- 权限和 CSRF；
- 键盘操作；
- 浏览器兼容。

Playwright 只用于测试本项目网页；不得用于未授权外部平台抓取。


---

# 18. 可观测性、告警与事故管理

## 18.1 可观测性目标

必须能够回答：

- 当前发生了什么；
- 从什么时候开始；
- 影响哪些账户、策略、模型、订单和数据源；
- 是否正在扩大风险；
- 自动系统采取了什么动作；
- 如何复现；
- 恢复是否安全。

## 18.2 指标设计

指标使用低基数标签，禁止把 order ID、symbol 全量或错误文本作为高基数标签。

### 系统指标

- CPU/GPU/RAM/磁盘；
- 文件描述符；
- 线程/任务；
- event loop lag；
- 数据库连接和锁；
- 队列深度；
- API 延迟和错误率；
- WebSocket 连接和重连；
- GC 和进程重启。

### 数据指标

- 每 Provider 数据延迟；
- sequence gap；
- rows/events per second；
- 缺失、重复、quarantine；
- schema drift；
- 时间偏差；
- checkpoint；
- 数据成本和配额。

### 模型和研究指标

- 推断延迟；
- 异常/超时；
- 预测分布；
- 校准；
- OOD；
- abstain；
- 当前模型版本；
- 训练队列和资源；
- 实验失败率。

### 交易和风险指标

- order intents；
- submitted/accepted/rejected/unknown；
- fills/partial fills；
- execution latency；
- slippage；
- reconciliation mismatch；
- ledger lag；
- exposure、margin、drawdown；
- risk rejects；
- circuit breaker state；
- kill switch。

## 18.3 结构化日志

JSON 日志字段至少包括：

```text
timestamp_utc
level
service
version
host
process_id
trace_id
span_id
correlation_id
event_type
account_scope
strategy_id
model_version_id
order_intent_id
error_code
message
```

敏感字段过滤：

- API key/secret；
- authorization header；
- Cookie/session；
- 原始用户个人信息；
- 完整外部付费正文；
- 账户密钥；
- 不必要的余额详情。

错误堆栈可以保留，但必须经过秘密扫描。

## 18.4 分布式追踪

OpenTelemetry 覆盖：

```text
market event
→ feature
→ inference
→ signal
→ portfolio
→ risk
→ execution
→ venue response
→ fill
→ ledger
→ read model
```

交易关键路径采样率可高于普通查询。追踪不能成为交易路径单点故障；导出失败时降级而非阻塞风险动作。

## 18.5 告警等级

```text
SEV0: 可能造成立即且不可控资金风险
SEV1: 实盘/Canary 核心路径失效或重大对账差异
SEV2: 数据、模型、策略或基础设施显著降级
SEV3: 研究、容量或非关键功能异常
INFO: 变更、恢复和趋势通知
```

SEV0/SEV1 必须有独立通知渠道和升级策略。告警合并、去抖、抑制和维护窗口要配置，不能产生告警风暴。

## 18.6 必需告警

- 账本不平衡；
- 账户/仓位/订单对账失败；
- 未知订单状态超过阈值；
- 风险状态改变；
- loss/drawdown/margin 阈值；
- 数据或账户流陈旧；
- 交易所断线；
- 订单拒绝激增；
- 时钟偏差；
- 磁盘不足；
- 数据库备份失败；
- 秘密扫描命中；
- 模型 OOD/校准异常；
- 发布或配置哈希变化；
- Live 解锁和到期；
- Changelog 检测到破坏性变化。

## 18.7 事故生命周期

```text
OPEN
ACKNOWLEDGED
MITIGATING
MONITORING
RESOLVED
POSTMORTEM_REQUIRED
CLOSED
```

每个 SEV0/SEV1 生成：

```text
reports/incidents/<incident_id>/timeline.md
reports/incidents/<incident_id>/evidence.json
reports/incidents/<incident_id>/postmortem.md
reports/incidents/<incident_id>/followups.yaml
```

Postmortem 包括事实、影响、检测、响应、根因、促成因素、修复、测试和责任到期时间，不使用含糊“人为失误”作为唯一根因。

## 18.8 Runbooks

至少建立：

```text
DATA_STALE.md
ORDER_UNKNOWN.md
RECONCILIATION_FAILURE.md
LEDGER_IMBALANCE.md
VENUE_DISCONNECT.md
MARGIN_RISK.md
MODEL_DRIFT.md
DATABASE_FAILURE.md
DISK_FULL.md
SECRET_LEAK.md
LIVE_KILL_SWITCH.md
RESTORE_FROM_BACKUP.md
```

每个 Runbook 有检测、立即动作、禁止动作、证据收集、恢复条件和演练记录。

---

# 19. 安全、秘密、供应链与威胁模型

## 19.1 威胁模型

至少考虑：

- 交易所密钥泄露；
- 网页面向公网暴露；
- 外部源码恶意行为；
- 文本提示词注入；
- 模型权重或依赖供应链污染；
- 数据投毒和错误供应商；
- 本地恶意软件；
- CI 日志泄密；
- 备份未加密；
- API 重放和 CSRF；
- DNS/证书/网络劫持；
- 交易所账户接管；
- 研究环境横向移动到实盘；
- 误配置放大杠杆；
- AI 生成代码引入隐蔽后门。

输出 `reports/security/THREAT_MODEL.md`，每个威胁有资产、攻击面、控制、残余风险和测试。

## 19.2 网络隔离

- 研究工作站和实盘主机使用不同凭据。
- 实盘数据库不对公网开放。
- Web 看板优先私网/VPN。
- 交易进程仅能访问所需交易所和基础设施。
- LLM/外部网络访问与实盘网络隔离。
- 数据采集账号和交易账号分离。
- 防火墙和出站白名单在可行时启用。

## 19.3 交易所密钥

- 禁用提现；
- 最小权限；
- 独立子账户；
- IP 白名单；
- 定期轮换；
- 不在命令行参数中传递；
- 不写入 shell history；
- 进程权限最小化；
- 读取后不打印；
- 支持快速吊销；
- Paper/Testnet 与 Live 使用完全不同密钥。

## 19.4 软件供应链

- 精确 lockfile；
- SBOM；
- 依赖漏洞扫描；
- PyPI/npm 来源固定；
- 关键包哈希验证；
- 容器镜像固定 digest；
- 最小基础镜像；
- 禁止未经审计安装来源脚本；
- 模型权重记录来源、许可和 SHA-256；
- 第三方仓库只读克隆并固定 commit；
- 自动升级只创建 PR/提案，不直接部署。

## 19.5 源码安全

CI 至少执行：

- Ruff/Pyright；
- 单元和属性测试；
- Semgrep 或等价 SAST；
- Bandit 或适当 Python 安全扫描；
- secret scanning；
- 依赖和许可证扫描；
- 前端 lint/type/test；
- 容器扫描；
- IaC 检查。

自动修复不得修改交易逻辑而不经过测试和审查。

## 19.6 AI 和外部内容安全

- 外部文本、HTML、图片、音频、视频、二维码和链接全部标记为 untrusted；
- RAG 内容与 system/developer/tool 指令物理和逻辑分层；
- 进入 LLM 前使用内容防火墙、长度限制、Unicode 规范化和注入检测；
- LLM 只获得最小化工具白名单和 JSON Schema；
- URL 获取、文件解析和模型推理分离，LLM 不能任意联网；
- 无秘密上下文、无实盘账户数据、无交易工具；
- 不同来源按 `SourceProcessingPolicy` 决定本地/云推理、保留和训练；
- 受限 X/Reddit/社区内容不得被用于未经许可的模型训练或微调；
- 云模型必须配置不训练、最小保留和区域/合规要求；
- 所有事实输出附 Evidence IDs；无证据内容只能标记为 hypothesis；
- 输出经过 schema、确定性校验、证据覆盖和测试验证；
- 删除/编辑内容传播到对象存储、索引、向量库、缓存和 Dashboard；
- 提示和响应按数据分类保留或脱敏；
- AI 不能关闭审计、风险、来源政策或许可检查。

## 19.7 数据分类

```text
PUBLIC
INTERNAL
CONFIDENTIAL
SECRET
RESTRICTED_LICENSE
```

每类定义存储、日志、备份、共享、云处理和保留政策。付费数据和社区导出不得被打包到公开仓库。

## 19.8 Web 安全

- 严格 CSP；
- XSS/HTML 清洗；
- CSRF；
- 参数化查询；
- SSRF 防护；
- 上传类型、大小和压缩包限制；
- 下载权限；
- 会话和 OIDC 安全；
- API rate limit；
- 审计写操作；
- 依赖安全头；
- 禁止前端 source map 暴露敏感实现，按环境配置。

## 19.9 备份和恢复

备份：

- PostgreSQL；
- 配置和发布清单；
- 账本事件；
- 数据清单；
- 模型/策略 Registry 元数据；
- 关键报告和事故材料；
- Web 用户布局，可选。

原始大规模公共数据可以按成本重下，但数据清单和不可重建的用户资料必须备份。

要求：

- 加密；
- 至少一份离机；
- 保留策略；
- 定期恢复演练；
- 恢复后重新对账；
- 记录 RPO/RTO。

## 19.10 Live 环境防误触

- Live 配置目录和二进制显著标识；
- shell prompt/页面状态明显；
- 发布包签名；
- 账户余额上限；
- 命令需要环境和账户双重匹配；
- 默认 Dry Run；
- 测试不能读取 Live secret；
- CI 永远没有 Live secret；
- 任何演示数据与 Live 清晰分区。

---

# 20. 部署、CI/CD 与灾难恢复

## 20.1 环境分层

```text
DEV
CI
RESEARCH
PAPER
SHADOW
TESTNET
CANARY
LIVE
```

数据库、密钥、账户和配置隔离。禁止通过一个布尔变量在同一进程中随意切换全部环境。

## 20.2 本地开发

Docker Compose 至少支持：

- PostgreSQL/TimescaleDB；
- Redis，可选；
- MLflow；
- API；
- Web；
- Prometheus；
- Grafana；
- Loki；
- Alloy；
- Alertmanager；
- MinIO，可选。

开发依赖可按 Profile 启动，避免 64GB 内存被无意义占满。

## 20.3 生产部署原则

- 构建一次，多环境运行；
- 容器或包固定 digest/hash；
- 数据库迁移向前兼容并有回滚；
- 交易进程滚动升级前进入安全状态；
- 先 Shadow/Paper 验证新版本；
- 变更窗口和回滚计划；
- 部署后自动 smoke、对账和健康检查；
- 未通过时自动回滚并保持 `HALTED/REDUCE_ONLY`。

## 20.4 CI Pipeline

建议阶段：

```text
lint
→ typecheck
→ unit/property
→ contract
→ security/license
→ build
→ integration
→ accounting/risk
→ replay golden tests
→ frontend tests
→ e2e
→ performance smoke
→ artifact/SBOM/sign
```

耗时测试可分层，但合并到主分支必须满足定义的 required checks。

## 20.5 CD Pipeline

- 自动部署仅允许 DEV/CI/PAPER；
- TESTNET 需要审批；
- CANARY/LIVE 必须人工批准和签名；
- 发布记录包含 commit、镜像 digest、配置、迁移、工件和审批；
- 不能由 LLM 独立批准。

## 20.6 数据库迁移

- Alembic 迁移不可修改已发布历史文件；
- 大表迁移先影子验证；
- 锁时间有预算；
- Read Model 可重建；
- 账本/订单核心表禁止破坏性迁移无备份；
- schema version 与服务兼容矩阵记录。

## 20.7 灾难场景

演练：

- 数据库丢失；
- 交易主机损坏；
- 网络分区；
- DNS/证书问题；
- 磁盘损坏；
- 账户流中断；
- 交易所 API 大改；
- 错误部署；
- 密钥泄漏；
- 账本损坏；
- 备份不可恢复。

恢复后必须从交易所事实、事件日志和账本重建，并进入人工对账，不得自动恢复交易。

---

# 21. 配置、CLI 与开发者接口

## 21.1 配置层级

```text
schema defaults
→ configs/base
→ configs/environments/<env>
→ local non-secret override
→ secret references
→ signed release override
```

未知字段报错。关键数值记录单位。配置解析结果和哈希写入启动日志。

## 21.2 示例配置结构

```yaml
runtime:
  environment: "paper"
  timezone_display: "Asia/Tokyo"
  live_trading: false

data:
  lake_root: "data"
  providers: ["binance_public"]
  max_clock_drift_ms: 500
research:
  experiment_backend: "mlflow"
  deterministic: true
risk:
  policy_ref: "configs/risk/paper_default.yaml"
execution:
  venue: "BINANCE_TESTNET"
  order_submission_enabled: false
web:
  bind: "127.0.0.1"
  port: 3000
observability:
  metrics_enabled: true
```

`live_trading` 单独为 true 仍然不能解锁实盘。

## 21.3 CLI 设计

统一命令：

```text
aqx doctor
aqx project init
aqx phase status
aqx phase validate P00
aqx access generate-requests
aqx data providers list
aqx data catalog
aqx data inventory-local --path <path>
aqx data ingest --provider <id> --dataset <name> --range <range>
aqx data validate --dataset-id <id>
aqx data build-pit --spec <file>
aqx intelligence import <export_dir>
aqx intelligence scan <source_id>
aqx intelligence extract <source_id>
aqx intelligence dedupe
aqx intelligence translate <strategy_id>
aqx features build --spec <file>
aqx labels build --spec <file>
aqx research run --hypothesis <file>
aqx research reproduce --run-id <id>
aqx backtest vector --strategy <id> --config <file>
aqx backtest event --strategy <id> --config <file>
aqx validate walk-forward --run-id <id>
aqx validate overfit --run-id <id>
aqx registry model promote --proposal <file>
aqx registry strategy promote --proposal <file>
aqx paper start --release <manifest>
aqx shadow start --release <manifest>
aqx testnet start --release <manifest>
aqx reconcile run --account <id>
aqx risk evaluate --proposal <file>
aqx system preflight
aqx system backup
aqx system restore-test
aqx web dev
aqx web build
aqx observability validate
aqx live preflight --release <manifest>
```

任何可能写入交易所的命令必须：

- 明确环境；
- 显示账户；
- 默认 dry-run；
- 需要发布包和风险政策；
- 在 Live 时需要独立解锁；
- 生成审计事件。

## 21.4 Exit Codes

稳定退出码：

```text
0   success
2   invalid input/config
3   dependency/environment failure
4   data quality failure
5   validation failure
6   risk rejection
7   reconciliation required
8   security/permission failure
9   external provider unavailable
10  internal invariant violation
```

脚本和 CI 不得解析自然语言判断成功。

## 21.5 OpenAPI 和 schema

- FastAPI 生成 OpenAPI；
- 前端客户端由 schema 生成；
- 破坏性 API 变更需要版本升级和迁移期；
- WebSocket schema 单独版本化；
- Pydantic/JSON Schema 用于配置、工件和事件；
- schema fixtures 进入契约测试。

## 21.6 开发者文档

至少生成：

```text
docs/architecture.md
docs/domain_model.md
docs/data_model.md
docs/time_semantics.md
docs/accounting.md
docs/risk.md
docs/execution.md
docs/research.md
docs/intelligence.md
docs/web_dashboard.md
docs/security.md
docs/runbooks.md
docs/adding_provider.md
docs/adding_strategy.md
docs/adding_model.md
docs/adding_exchange.md
```

---

# 22. 测试、质量门槛与验收方法

## 22.1 测试金字塔

### 单元测试

纯函数、公式、状态转换、舍入、配置和 parser。

### 属性测试

- 账本平衡；
- 重放幂等；
- 风险不放大批准目标；
- 时间切分无泄漏；
- 订单状态单调；
- 组合约束永远满足；
- 数据转换行守恒或有解释。

### 契约测试

- 交易所 API；
- 数据供应商；
- Nautilus Adapter；
- OpenAPI；
- WebSocket；
- 数据 schema；
- 数据库迁移。

### 集成测试

- 采集到 Parquet；
- 特征到模型；
- 信号到风险；
- 订单到成交和账本；
- 账本到 Read Model 和 Web。

### 回放测试

保存最小但高价值的历史事件夹具：

- 正常行情；
- 高波动；
- sequence gap；
- 部分成交；
- 交易所异常；
- 资金费率结算；
- 下线/规则变化。

### Chaos 测试

- 网络断开；
- 超时；
- 进程 kill；
- 数据库暂不可用；
- 乱序/重复消息；
- 磁盘满；
- 慢时钟；
- 模型超时。

### E2E

从固定市场事件到 Dashboard 显示，验证 ID、金额和状态全链路。

## 22.2 Golden Tests

以下必须有黄金夹具：

- PnL/账本；
- 费用和资金费率；
- 仓位反手；
- 订单未知状态恢复；
- 组合约束；
- 回测统计；
- Read Model；
- Web 关键页面快照。

黄金结果修改需 ADR 和审查，不能为了让测试通过随意更新。

## 22.3 Mutation Tests

对风险、账本、订单状态机、时间切分和费用公式执行 mutation testing。关键模块的 mutation score 低于设定阈值不得通过阶段验收。

## 22.4 性能测试

基准：

- Parquet ingest/query；
- 特征计算；
- backtest events/s；
- 模型训练和推断；
- order/risk path p99；
- ledger postings/s；
- Read Model 刷新；
- API 和 Web；
- 内存峰值；
- 长时间运行泄漏。

性能优化前先有 profiler 和基准。禁止以牺牲正确性、精度和审计为代价。

## 22.5 确定性

- 测试固定时区、locale 和随机种子；
- 控制线程和 GPU 非确定性，无法完全控制时明确记录；
- 外部 API 用录制夹具，不让 CI 依赖实时网络；
- 时间使用可注入 Clock；
- UUID/ID 可在测试中注入；
- 同一回放必须产出相同经济事件哈希。

## 22.6 代码覆盖与关键性

不以单一覆盖率数字替代质量。按关键性设门槛：

- 风险、账本、订单、对账：分支覆盖、属性测试和 mutation 均高要求；
- 数据 parser：契约和坏输入测试；
- 研究模型：重点在可复现和验证，不追求每个第三方模型内部覆盖；
- Web：关键业务流和状态覆盖。

## 22.7 验收证据

每个阶段的 `TEST_RESULTS.json` 至少：

```json
{
  "phase": "P00",
  "commit_sha": "...",
  "environment_fingerprint": "...",
  "suites": [],
  "passed": 0,
  "failed": 0,
  "skipped": 0,
  "known_flakes": [],
  "coverage": {},
  "mutation": {},
  "performance": {},
  "security_findings": [],
  "result": "pass|fail"
}
```

跳过项必须有理由和后续阶段，不得使用无条件 skip 隐藏失败。


---

# 23. 从零实施阶段路线图

## 23.1 阶段依赖图

```text
P00 项目启动与安全基线
  ↓
P01 领域内核与持久化骨架
  ↓
P02 数据底座、Provider Registry 与本地资产清点
  ↓
P03 Binance 官方公共数据
  ↓
P04 OKX/Bybit/Deribit、X/Telegram/Bluesky 与首批事件情报
  ↓
P05 双重记账、PnL 与对账内核
  ↓
P06 双回测引擎、成本、成交和保证金模拟
  ↓
P07 特征、标签、简单基线与严格验证
  ↓
P08 研究工厂、Model Council 与 AI 研究代理
  ↓
P09 外部知识与聚宽策略情报工程
  ↓
P10 全球事件智能、宏观、链上、DeFi 与多源融合
  ↓
P11 组合构建与独立风险引擎
  ↓
P12 执行系统、账户流与 Testnet
  ↓
P13 Paper、Shadow、历史回放与 Chaos 验证
  ↓
P14 Read Model、API 与看板设计系统
  ↓
P15 完整网页版看板与端到端下钻
  ↓
P16 可观测性、安全加固、部署与灾备
  ↓
P17 付费数据源 Bake-off 与采购决策
  ↓
P18 Canary 实盘就绪审查与持续运营制度
```

允许在某阶段内部并行执行无冲突任务，但不得跨越尚未通过的安全和正确性依赖。

---

## P00：项目启动、规格固化与安全基线

### 目标

在空目录中建立可重复、默认安全、可被 Codex 持续执行的项目骨架。第一轮 Codex 只完成此阶段并停止。

### 任务

1. 初始化 Git 仓库和主分支保护建议。
2. 复制本总任务书到 `docs/spec/AegisQuant_Master_Taskbook_v3_1.md`，计算 SHA-256。
3. 生成需求可追踪矩阵，将每个“必须/禁止”映射到阶段和测试。
4. 建立完整目录结构，但不得生成虚假业务实现。
5. 探测 OS、WSL、CPU、RAM、GPU、CUDA、磁盘、网络、Docker、Python 和 Node。
6. 选择 Python 3.13 精确补丁版；测试 Python 3.14 候选但不强制采用。
7. 使用 `uv` 建立 Python 项目和 lockfile。
8. 使用 Node 24 LTS、pnpm、Next.js/React/TypeScript 建立最小可构建前端。
9. 建立 Ruff、Pyright、pytest、pre-commit、前端 lint/type/test。
10. 评估 NautilusTrader 最新稳定非预发布版本：安装、导入、最小回放、Python 兼容、许可证和版本记录。
11. 如果当前只有新主版本 RC，则选择最新 GA 稳定版并生成 ADR。
12. 建立依赖矩阵、SBOM、许可证和秘密扫描。
13. 建立 `LIVE_TRADING=false` 多重锁：配置、代码常量保护、无 Live Adapter 注册、测试断言。
14. 建立阶段状态文件和报告模板。
15. 生成用户访问请求，不包含秘密：本地数据路径、聚宽能力、X Developer 项目、Telegram 专用研究账号/API、YouTube/GitHub、新闻订阅、Testnet 账号和风险偏好。
16. 建立 `SourceProcessingPolicy` schema、来源许可矩阵和默认拒绝策略。
17. 生成事件本体初稿、官方来源 allowlist 模板和关键实体目录模板。
18. 生成威胁模型初稿和安全政策。
19. 配置基础 CI；若没有远程 Git，则提供本地 CI 脚本。
20. 建立 ADR 机制和编码规范。
21. 生成 `CODEX_BOOTSTRAP.md`，规定后续每轮如何读取状态、执行当前阶段和停止。
22. 运行所有最小测试、构建和秘密扫描。

### 特殊产物

```text
state/HOST_CAPABILITIES.json
state/DEPENDENCY_MATRIX.json
state/REQUIREMENTS_TRACEABILITY.csv
reports/access/SOURCE_ACCESS_REQUESTS.md
reports/access/SOURCE_ACCESS_REQUESTS.yaml
reports/access/LOCAL_PATH_REQUESTS.md
reports/access/SECRET_SETUP_GUIDE.md
reports/access/NEWS_SOCIAL_ACCESS_MATRIX.md
reports/access/OFFICIAL_SOURCE_ALLOWLIST_TEMPLATE.yaml
reports/security/THREAT_MODEL_DRAFT.md
docs/adr/ADR-0001-runtime-and-version-policy.md
docs/adr/ADR-0002-event-engine-selection.md
docs/adr/ADR-0003-live-lock.md
```

### 验收

- 空环境按 README 能完成安装、lint、typecheck、test 和前端 build。
- lockfile 完整且无浮动 `latest`。
- 所有导入不产生网络、下单或秘密读取副作用。
- 仓库秘密扫描为零命中。
- 前端显示明确的 `DEVELOPMENT / LIVE LOCKED` 空状态。
- Nautilus 版本选择有实际兼容测试，不仅是文档判断。
- `LIVE_TRADING` 无法通过单一环境变量启用。
- 所有阶段报告存在且 `P00` 状态为 `accepted`。
- 完成后停止，不得开始 `P01`。

---

## P01：领域内核、事件契约与持久化骨架

### 目标

建立不依赖交易所、数据库和 Web 框架的纯领域核心，以及 PostgreSQL 事件/Outbox/Registry 骨架。

### 任务

1. 实现强类型 IDs、UTC 时间、可注入 Clock、Decimal Money/Quantity/Price。
2. 实现 Instrument、Venue、Asset、Account、Environment。
3. 实现 MarketEvent、RawContentEnvelope、SourceIdentity、ClaimRecord、EventCluster、NarrativeState、EventImpactForecast、ForecastBundle、AlphaSignal、PortfolioProposal、RiskDecision。
4. 实现 SourceProcessingPolicy 与采集/推理/展示/删除边界的领域判定。
5. 实现 OrderIntent、OrderCommand、VenueOrder、Fill 和恢复案例领域对象。
6. 实现 JournalEntry、LedgerPosting、PositionLot 的 schema，不实现完整会计逻辑前先固化不变量。
7. 实现版本化序列化、schema migration 和兼容测试。
8. 实现统一错误码和重试分类。
9. 建立配置 schema、严格未知字段、内容哈希。
10. 建立 PostgreSQL、Alembic、Outbox、Inbox/幂等表和基础 Registry 表。
11. 建立事件 JSON Schema 与 Python round-trip 测试。
12. 建立领域属性测试：金额、时间、状态、序列化、幂等键。
13. 建立数据库迁移测试和事务边界文档。

### 特殊产物

```text
docs/domain_model.md
docs/time_semantics.md
docs/event_contracts.md
docs/database_boundaries.md
schemas/events/
schemas/config/
```

### 验收

- `domain` 包无 FastAPI、ORM、交易所 SDK 依赖。
- 无 naive datetime；静态检查可阻止。
- Money/Quantity 不能与普通 float 隐式混合。
- 事件 round-trip 保持经济字段与版本。
- Inbox/Outbox 重放不会重复消费。
- 数据库从空库迁移和回滚测试通过。
- 关键不变量有属性测试。

---

## P02：数据底座、Provider Registry 与本地资产清点

### 目标

建立不可变 Parquet 数据湖、清单、point-in-time 语义、质量框架和用户现有资产的只读扫描器。

### 任务

1. 实现 Provider Registry 和访问/许可状态。
2. 实现 RAW/BRONZE/SILVER/GOLD 路径、写入原子性和文件清单。
3. 实现内容哈希、断点续传、schema registry、转换 lineage。
4. 实现 DuckDB 查询层和 Polars/PyArrow 转换。
5. 实现通用数据质量引擎和 quarantine。
6. 实现 `event_time/available_time/ingest_time/revision_time`，以及内容的 published/observed/modified/deleted/engagement snapshot 时间。
7. 实现文本/社交 raw archive、revision/tombstone、受限内容加密和删除传播骨架。
8. 实现 point-in-time join 和专门泄漏测试。
9. 实现本地目录扫描：文件类型、大小、时间范围、schema、哈希、重复、可能的策略结果。
10. 扫描只读，不执行代码、不修改原文件、不自动移动。
11. 实现 import proposal，而不是直接导入未知文件。
12. 实现来源政策 Registry 和采集前强制 gate。
13. 建立 Data Catalog 和最小 CLI。
14. 使用合成和小型真实公共样本验证 200GB 级目录与大量短文本事件的性能。
15. 生成存储容量、备份和生命周期建议。

### 外部输入

- 如果用户提供本地路径，执行真实只读清点。
- 如果未提供，使用大规模合成目录夹具验证扫描器，并保留访问请求；不伪称已扫描用户数据。

### 特殊产物

```text
reports/data/LOCAL_ASSET_INVENTORY.md
reports/data/LOCAL_ASSET_INVENTORY.parquet
reports/data/DATA_LAKE_BENCHMARK.md
reports/data/PIT_LEAKAGE_TESTS.md
data/catalogs/provider_registry.yaml
```

### 验收

- 输入同一文件得到同一 dataset/hash。
- 中断写入不会产生已登记但不完整数据集。
- 修订不会覆盖原始版本。
- PIT join 属性测试阻止未来记录。
- quarantine 数据不能进入 Gold。
- 100GB 级目录扫描估算和内存基准合理，不把全部文件加载到 RAM。

---

## P03：Binance 官方公共市场数据与主数据

### 目标

完成首个生产级公共行情适配器和可回放数据集，不接触交易私钥。

### 任务

1. 根据 Binance 官方最新文档建立 REST/WS 契约清单。
2. 实现 Spot 和 USDⓈ-M Futures instrument snapshots。
3. 实现 Kline、trade/aggTrade、bookTicker、depth、mark/index、funding、OI 等可用数据。
4. 实现 WebSocket 连接、订阅、心跳、重连、限频和监控。
5. 实现 order book snapshot + incremental rebuild、sequence gap 恢复。
6. 实现历史下载、分页、checkpoint、重试和原始响应归档。
7. 实现 symbol/master data 的时点版本。
8. 实现交易日边界和未完成 K 线标记。
9. 将官方数据转换到统一 Silver schema。
10. 对 Kline 与 trades 聚合、盘口和 ticker 做一致性检查。
11. 建立录制夹具和离线 replay。
12. 建立 Binance Changelog Watcher 基础。
13. 验证 Nautilus Binance 数据适配与本项目数据语义；记录差异。

### 验收

- 24 小时连续公共流测试无无法解释 sequence gap。
- 人工断网后可自动重建盘口和 watermark。
- 重复、乱序和迟到事件处理明确。
- instrument rule snapshot 可按时间查询。
- 所有数据有来源、时间和质量状态。
- CI 不调用实时 API；契约夹具可离线运行。
- 无任何账户或下单权限。

---

## P04：OKX、Bybit、Deribit 与首批全球事件/社交情报

### 目标

建立统一但不掩盖差异的多交易所公共数据层。

### 任务

1. 实现 OKX 公共 market/instrument Adapter。
2. 实现 Bybit 公共 market/instrument Adapter。
3. 实现 Deribit futures/options 公共 Adapter。
4. 支持各自 WebSocket、快照、sequence、限频和状态页。
5. 建立 spot/perpetual/future/option 的统一映射。
6. 显式处理正向/逆向、quote/settlement、合约乘数、expiry 和 strike。
7. 构建 Canonical Asset/Pair/Exposure。
8. 实现跨所 ticker、funding、basis、OI 和流动性对照。
9. 建立多源时钟偏差和 lead-lag 数据集。
10. 建立每个交易所 Changelog Watcher。
11. 验证 Nautilus 相应 Adapter；无法使用时保留本项目原生路径。
12. 生成地域、账户和产品权限待用户确认清单。

### 验收

- 相同经济暴露不会因 symbol 同名而错误合并。
- 逆向合约 PnL/数量单位测试正确。
- 期权字段和 IV 来源明确。
- 每个 Adapter 有统一契约测试与交易所特定测试。
- 任一 Provider 断线不会污染其他 Provider 数据。
- 跨所比较含时间、quote asset 和质量过滤。

---

### 事件与社交情报并行任务

1. 建立官方来源目录：交易所、稳定币、主流协议、监管机构、中央银行、ETF/资产管理人和关键基础设施。
2. 实现 RSS/Atom、官方网页变更和 GDELT 最小适配器。
3. 实现 X 官方 API Adapter 的契约、mock、额度、filtered stream、recent/full-archive search 和删除/修改同步；没有凭据时使用录制夹具，不伪称已连通。
4. 实现 Telegram Bot API Adapter；可选 MTProto 专用研究账号模式必须独立安全评审和人工登录。
5. 实现 Bluesky Firehose/Jetstream Adapter 与断点回补。
6. 实现 GitHub Release/Security Advisory/Webhook Adapter。
7. 实现 YouTube 频道/视频元数据和获准直播聊天 Adapter。
8. 实现 RawContentEnvelope、SourceIdentity、revision/tombstone 和 engagement snapshot 存储。
9. 实现语言、去重、实体链接、Claim/Event 最小流水线；本阶段只需规则和轻量基线，不使用大型 LLM 自动交易。
10. 建立来源许可、云推理和展示 gate；Reddit/Discord/微博/TikTok 默认关闭。
11. 用合成和少量公开许可样本做 point-in-time 重放、断流和删除传播测试。

### 事件情报额外验收

- X/Telegram/Bluesky 等任一来源不可用时，系统有明确降级并不影响交易账本。
- 同一新闻的大量转载不会被计为大量独立证据。
- 删除或修改事件可传播至缓存和 Read Model 测试环境。
- 外部提示词注入不能调用工具或改变配置。
- 当前互动数不能被错误加入历史特征。
- 没有用户凭据时，契约和夹具可验收，但访问状态必须为 `awaiting_credentials`。

## P05：双重记账、PnL、头寸和对账内核

### 目标

在任何策略开发前，建立权威资金事实系统。

### 任务

1. 实现 Chart of Accounts 和版本化分录模板。
2. 实现现货买卖、永续开平、加减仓和反手。
3. 实现 FIFO/平均成本等明确 lot 政策；选择并写 ADR。
4. 实现正向/逆向合约 PnL。
5. 实现手续费、资金费率、借贷和外部划转。
6. 实现 realized/unrealized 与估值快照。
7. 实现权威权益和 PnL 分解。
8. 实现订单/成交/账本幂等关系。
9. 实现账户快照比较与 Reconciliation Case。
10. 使用模拟交易所夹具实现启动、持续和断线对账。
11. 实现每日签名快照和重建。
12. 建立完整属性、Golden 和 mutation 测试。

### 验收

- 所有分录借贷平衡。
- 同一 Fill 重放任意次数只产生一次经济事实。
- 随机成交序列可由账本重建仓位和权益。
- 本地与模拟交易所差异能分类，不会静默修正。
- 账本从事件重建后的哈希一致。
- 浮点数不能进入会计 API。

---

## P06：向量化与事件驱动回测、成本和保证金

### 目标

建立从快速研究到高保真回放的统一验证基础。

### 任务

1. 实现 Vector Backtest 接口和基准策略。
2. 集成 NautilusTrader 最新稳定内核，或通过领域协议封装等价 Event Engine。
3. 统一订单、成交、账本和指标输出。
4. 实现历史手续费、funding、borrow、spread、slippage 和 impact。
5. 实现 bar/trade/L2 多级成交模型。
6. 实现延迟、部分成交、撤单竞态和 unknown state 模拟。
7. 实现 margin、leverage bracket、mark、liquidation 近似。
8. 实现多腿和跨所非原子执行。
9. 实现历史 instrument rules。
10. 实现性能指标、交易指标和回测工件。
11. 建立 vector/event 一致性测试。
12. 实现成本、延迟、流动性和故障压力场景。
13. 对事件吞吐、内存和稳定性做基准。

### 验收

- 零成本、即时成交简化场景中双引擎结果一致。
- 成本和资金费率通过手算 Golden Case。
- event replay 多次结果相同。
- 交易规则变化会影响历史订单合法性。
- 断线/部分成交/多腿失败场景不会产生账本不平衡。
- 回测输出包含订单、成交、账本和复现命令。

---

## P07：特征、标签、简单基线与反过拟合验证

### 目标

建立第一套完整、朴素、可信的研究基准。在此阶段不追求大型 AI 模型。

### 任务

1. 实现 Feature Registry、Feature Snapshot 和批/增量 parity。
2. 实现收益、趋势、波动率、流动性、资金费率、基差、横截面和事件最小基础特征。
3. 事件基础特征至少包括官方/非官方、独立来源数、事件类型、novelty、stance、传播速度、市场已反映程度和数据质量；不得只做整篇情绪。
4. 实现净收益、三分类、分位数、波动率、MAE/MFE、执行和事件影响基础标签。
5. 实现 point-in-time Universe。
6. 实现 walk-forward、purge、embargo、CPCV/CSCV 基础。
7. 实现 PBO、DSR/PSR 和多重试验报告。
8. 实现基线策略：现金、持有、简单趋势、横截面、资金费率/基差、官方事件风险覆盖和极保守事件候选。
9. 实现线性、Logistic、Elastic Net、HAR-RV、简单状态模型，以及 Market-only/Event-only/Fused 三组公平基线。
10. 实现费用 1x/1.5x/2x、事件延迟、互动快照、参数扰动和状态切片。
11. 建立最终 holdout 的访问锁和审计。
12. 生成第一份 `BASELINE_SCOREBOARD.md`，包含事件增量和负结果。
13. 如果用户提供旧 R331，作为不可修改外部基准导入并单独标记其数据和成本口径。

### 验收

- 任何随机 shuffle 时间切分在代码层被阻止。
- 未来特征和标签泄漏测试可主动捕获故意注入的错误。
- 所有试验包括失败项可查询。
- 简单策略净收益与手算/独立实现一致。
- 报告明确 gross 与 net，不用单一 Sharpe 排名。
- 最终 holdout 在冻结前不可读。

---

## P08：研究工厂、Model Council 与 AI 研究代理

### 目标

在可靠基线上引入可控自动化研究和多模型竞争。

### 任务

1. 部署 MLflow、Experiment Ledger 和 Artifact Registry。
2. 集成 Optuna，强制记录全部 trial 和搜索预算。
3. 实现 Hypothesis Spec、队列和资源预算。
4. 实现 LightGBM、CatBoost、XGBoost 统一接口。
5. 实现至少两个轻量深度时序候选。
6. 建立 Chronos-2/Moirai 2/TimesFM 3/Kronos 插件接口；按许可和硬件选择有限评测。
7. 实现预测分布、校准、conformal/区间和 abstain。
8. 实现 OOF stacking 和状态门控。
9. 实现 drift/OOD 基础监控。
10. 建立 Champion/Challenger 和 Model Card。
11. 建立 LLM Provider 抽象、RAG 安全边界、Source Policy Gate 和结构化输出。
12. 实现 Event Expert Committee：Extractor、Entity、Source、Corroboration、Skeptic、Market、On-chain、Impact 和 Arbiter。
13. 实现 Claim/Event Graph、证据覆盖率、冲突、事件状态和多时间尺度 EventImpactForecast。
14. 实现 Market-only/Event-only/Fused 公平比较与 abstain。
15. AI 只能创建 Hypothesis/Experiment/Event Proposal，不可自动发布或下单。
16. 对 GPU 显存、训练时间、事件推断延迟、X/新闻调用和云模型成本做预算。
17. 运行至少一个完整 Model Council 公平比较和一个历史事件重放。

### 验收

- 复杂模型不因类别自动获得优势；结果可能被淘汰。
- 所有模型使用相同 split、成本和搜索预算报告。
- AI 输出无效 schema 时不会启动实验。
- 外部文本提示词不能获得工具或秘密。
- 模型能因低置信度/高分歧输出 abstain。
- 基础模型权重和许可证有哈希与记录。
- 4070 Ti 上的资源上限得到遵守，OOM 有可恢复策略。

---

## P09：外部知识与聚宽策略情报工程

### 目标

从零建立合规的来源归档、静态分析、Strategy IR、审计、去重和加密迁移系统。

### 任务

1. 实现 Source Manifest、Artifact、Rights、Evidence Span 数据模型。
2. 实现公开索引候选发现，但不尝试绕过登录或地区限制。
3. 实现聚宽/其他平台手工导出包 importer。
4. 可选制作本地浏览器扩展，只导出用户主动打开且有权访问的当前页面。
5. 实现 HTML/Markdown/Notebook/Python/附件安全归档。
6. 实现 AST 静态分析和危险代码检测。
7. 实现平台 API 识别、参数提取和时间/成交语义检查。
8. 实现 Strategy IR 和双通道抽取：规则解析 + AI 候选，证据核对。
9. 实现偏差、成本、未来函数和幸存者审计。
10. 实现 Alpha 原语、AST/IR/信号/收益多层去重。
11. 实现传统市场到加密市场的迁移记录。
12. 从零重写至少 3 个高迁移价值的简单候选，并统一回测；不能使用来源收益作为结论。
13. 完成 NautilusTrader、LEAN、Qlib、VeighNa、Hummingbot、Freqtrade/FreqUI、OpenBB 和 Grafana 框架评审。
14. 生成聚宽及其他平台后续资料请求队列。

### 外部输入

- 用户若尚未提供聚宽导出，Importer、扩展和合成夹具仍可完成；真实来源目录标记为等待资料，不伪造正文。
- 不需要、也不得请求账号密码、Cookie 或验证码。

### 验收

- 未经静态审计的源码无法执行。
- 每个结构化规则可链接到证据或明确标记缺失。
- 相同策略的复制和改名可被聚类。
- 迁移策略有新的 AegisQuant 实现和新的验证结果。
- 权利状态未知的内容不会进入公开工件。
- 浏览器扩展无后台批量抓取、无秘密导出、无远程上报。

---

## P10：全球事件智能、宏观、链上、DeFi 与多源融合

### 目标

把 P04 的首批事件采集升级为可审计的实时事件知识图谱和 AI 联合判断系统，并接入低成本高潜力的宏观、链上与 DeFi 数据。

### 任务

1. FRED/ALFRED Adapter 和 vintage-aware 数据集。
2. Coin Metrics Community Adapter。
3. Dune 查询 Registry、SQL 版本和结果清单。
4. DeFiLlama Adapter。
5. 扩展交易所、项目、监管、法院、中央银行、ETF/发行方官方来源目录。
6. GDELT 作为广域事件发现；聚合结果必须回溯原始来源。
7. 完成 X、Telegram、Bluesky、YouTube、GitHub 的生产级只读接入、额度、断流和回补；仅启用用户已提供且许可通过的来源。
8. 实现多语言规范化、可审计翻译、近重复/转载家族和跨平台实体链接。
9. 实现 Claim 抽取、支持/反驳、EventCluster、NarrativeState 和事件状态机。
10. 实现来源身份、领域历史准确性、修正率、官方确认、操纵风险和独立来源估计。
11. 实现 Fast Path 与 Deep Path AI 委员会、Skeptic Agent、证据覆盖和 structured abstain。
12. 实现多资产、多时间尺度 EventImpactForecast，并与实时价格、盘口、OI、资金费率、基差和链上数据联合。
13. 构建 Market-only、Event-only、Fused、Risk-only 四组模型与策略消融。
14. 实现 event replay、延迟压力、future engagement 检测、revision/deletion 和 pre-trend/placebo 测试。
15. 建立人工标注、主动学习和事件本体版本管理。
16. 实现来源政策执行：本地/云推理、训练、展示、删除、导出和保留。
17. 实现 Dashboard 所需 Event Radar、Evidence Graph、Narrative Monitor、Source Monitor 和 Event Replay Read Models。
18. 无增量来源标记为监控/保留/退役，不强行加入方向模型；高价值风险监控可独立保留。

### 验收

- ALFRED 回测使用当时 vintage，不使用最终修订值。
- Dune 查询和参数完全可重现。
- 新闻、推文和频道消息的更新/删除不会覆盖首次版本，互动指标按快照回放。
- 每个高影响 EventCluster 能回到原始证据、来源政策、AI 模型和冲突信息。
- 一百篇转载同源内容不会增加独立证据计数。
- Market-only/Event-only/Fused 的同预算 OOS 报告同时包含正负结果。
- 事件延迟增加后结果仍被如实报告，不能用零延迟美化。
- 外部源或 LLM 不可用时系统有降级路径，风险和交易基础设施继续工作。
- 来源许可不明、Reddit/Discord 等未批准来源保持禁用。
- 单一社交帖子无法绕过组合和风险层生成订单。

---

## P11：组合构建与独立风险引擎

### 目标

把模型和策略输出转换成受成本、容量和风险约束的目标组合，并保证风险不可绕过。

### 任务

1. 实现信号归一化、置信度折扣和 no-trade zone。
2. 实现协方差 shrinkage、因子和状态风险。
3. 实现风险预算、vol target 和 robust optimizer。
4. 实现资产、合约、策略、袖套、交易所、稳定币和相关簇约束。
5. 实现 turnover/impact/capacity 约束。
6. 实现 PortfolioProposal 和可解释贡献。
7. 实现独立 RiskSnapshot 和 RiskDecision。
8. 实现订单/资产/策略/账户级预交易限制。
9. 实现 NORMAL/CAUTION/REDUCE_ONLY/HALTED/RECOVERY。
10. 实现数据、模型、损失、保证金、流动性、交易所、安全和重大事件熔断器。
11. 实现官方安全事故、暂停提现、稳定币脱锚、重大监管和基础设施事件的签名风险剧本。
12. 传闻状态只允许监控、收紧限额或减仓，不允许由 LLM 自由全平。
13. 实现风险事件、告警和恢复前置条件。
14. 建立风险政策 schema、签名和版本。
15. 使用属性和 mutation 测试证明策略无法放大批准目标。
16. 使用压力场景验证组合和风险动作。

### 验收

- 所有 PortfolioProposal 必须经过风险决策才能生成 OrderIntent。
- 研究/模型进程无法导入或调用 Risk override。
- 风险数据陈旧时拒绝新风险。
- 自动只能向更安全状态迁移。
- 所有约束在随机测试中满足。
- Kill Switch 和 Reduce-only 行为可回放。
- 示例风险数值不会被误用于 Live；用户未确认时只允许 Paper。

---

## P12：执行、账户流、订单状态机与 Testnet

### 目标

完成 Binance 首个交易执行路径，并为其他交易所建立统一接口；仅 Testnet/模拟账户。

### 任务

1. 实现 Execution Adapter 和 Binance Testnet。
2. 验证 Nautilus Binance Execution Adapter；若不满足契约，使用领域层后的原生实现。
3. 实现 OrderIntent→OrderCommand。
4. 实现完整订单状态机和幂等 Client Order ID。
5. 实现账户 WebSocket、REST 快照、重连和对账。
6. 实现 timeout/unknown state 恢复。
7. 实现 partial fill、cancel/replace race、late event。
8. 实现动态 instrument rules 和量化。
9. 实现 maker/taker、time-bounded passive、TWAP 和 reduce-only。
10. 实现多腿 ExecutionGroup 和裸露上限。
11. 实现限频优先级和背压。
12. 将 Fill 原子写入账本/Outbox。
13. 实现启动、优雅关闭和崩溃恢复。
14. 为 OKX/Bybit/Deribit 建立执行适配骨架和契约，但不要求首批真实发送。
15. 建立 Testnet 端到端和故障测试。

### 外部输入

需要用户在本地秘密库配置 Testnet 凭据。若未提供，阶段可完成模拟和契约部分，但真实 Testnet 验收标记 `blocked`，不得伪造通过。

### 验收

- Testnet 可完成提交、部分成交/模拟、撤单、重连和重启恢复。
- 超时后不重复经济订单。
- 交易所和账本对账一致。
- 规则变化/非法精度在本地被拒绝。
- 风险拒绝的意图无法到达 Adapter。
- 无 Live 域名、密钥或账户可用。
- Chaos 场景不产生未知资金事实。

---

## P13：实时 Paper、Shadow、历史回放与 Chaos 验证

### 目标

让完整系统在不使用真实资金的情况下长期运行，验证模型、风险、执行和运营语义。

### 任务

1. 实现实时 Paper 订单和成交模型。
2. 实现 Shadow 模式，连接真实公共行情和可选只读账户状态，但不下单。
3. 将同一策略运行在历史回放、Paper 和 Shadow，比较语义。
4. 实现预测、目标、订单、实际可成交价格的差异分析。
5. 实现 7×24 运行守护和自动恢复。
6. 运行历史重大事件回放。
7. 注入网络、数据库、模型、数据源、时钟和进程故障。
8. 验证熔断器、Runbook 和告警。
9. 验证账本、Read Model 输入和每日对账。
10. 形成候选策略的 Paper/Shadow Scorecard。
11. 定义 Testnet 与真实市场差异，不把 Testnet PnL 当作证据。
12. 至少运行一个预定持续期的稳定性测试；测试时长由 Codex 根据阶段资源定义并写 ADR，不能用几分钟代替长期行为。

### 验收

- 完整链路可连续运行且内存无持续泄漏。
- 重启后状态恢复、无重复订单/账本。
- 数据陈旧和模型失败触发正确降级。
- Paper 成交误差有量化报告。
- Shadow 无任何写交易权限。
- 所有 SEV0/SEV1 演练有时间线和恢复证据。

---

## P14：Read Model、FastAPI 与看板设计系统

### 目标

建立权威读模型、稳定 API、实时流和高质量前端基础，不急于一次完成所有页面。

### 任务

1. 实现 Read Model 投影框架和可重建机制。
2. 实现 account、PnL、position、risk、strategy、model、order、data health 基础投影。
3. 实现 FastAPI `/api/v1`、OpenAPI、分页、过滤、错误码和健康检查。
4. 实现 WebSocket snapshot + sequence 增量协议。
5. 生成 TypeScript API 客户端和 schema 契约测试。
6. 建立 Next.js App Router、布局、导航、主题和权限。
7. 建立语义 Design Tokens、深浅色、密度、红绿习惯和数字格式。
8. 建立 Storybook 和通用组件。
9. 接入 ECharts 和 Lightweight Charts 的封装层。
10. 实现 Overview 与 `/intelligence` 高保真原型和真实 Read Model 数据。
11. 实现 loading/empty/stale/degraded/disconnected/error 全状态。
12. 实现无障碍和响应式基础。
13. 建立视觉回归、E2E 和性能基准。

### 验收

- 前端不连接交易核心数据库或交易所。
- PnL 与风险由服务端权威 Read Model 提供。
- WebSocket 丢序可通过 REST snapshot 恢复。
- Overview 满足性能目标或有基准和改进计划。
- 所有通用组件有完整状态 Story。
- 界面明确显示环境、Live lock、数据截至时间和权威状态。

---

## P15：完整网页版看板与端到端下钻

### 目标

实现第 17 章全部核心页面和跨模块追溯，达到可长期使用的个人量化工作台质量。

### 任务

1. 完成 `/live`。
2. 完成 `/performance`。
3. 完成 `/execution` 和 K 线交易回放。
4. 完成 `/strategies`。
5. 完成 `/models`。
6. 完成 `/market`。
7. 完成 `/intelligence`，含 Event Radar、Evidence Graph、Narrative Monitor、Source Monitor、Event Replay 和事件告警。
8. 完成 `/risk`。
9. 完成 `/research`。
10. 完成 `/research/intelligence`。
11. 完成 `/data`。
12. 完成 `/incidents`。
13. 完成 `/system`。
14. 完成 `/settings` 的安全范围。
15. 实现全局筛选、命令面板、导出和保存布局。
16. 实现信号→事件证据→模型→风险→订单→成交→账本的单击下钻。
17. 实现服务端下采样、虚拟表格和缓存。
18. 实现中文文案、tooltip、指标公式和时区。
19. 完成 WCAG 2.2 AA 审计和键盘流程。
20. 对桌面主流浏览器和窄屏状态做测试。
21. 建立产品级视觉回归和性能预算。

### 验收

- 用户可在 5 秒内判断权益、当日 PnL、风险、数据和对账状态。
- 任意订单可追溯完整决策链。
- 任意 PnL 指标可解释公式、来源和截至时间。
- 大表和长时序不冻结浏览器。
- 红绿切换不改变语义文本或可访问性。
- 默认无任意交易、Live 解锁或风险上限修改入口。
- 页面错误不会影响交易服务。

---

## P16：可观测性、安全加固、生产部署与灾备

### 目标

把已完成系统变成可运营、可告警、可恢复、可安全部署的服务。

### 任务

1. 接入 Prometheus、Grafana、Loki、Alloy、Alertmanager 和 OpenTelemetry。
2. 建立业务、交易、风险、数据、模型和基础设施仪表盘。
3. 建立 SEV0-3 告警、路由、去抖和维护窗口。
4. 建立第 18 章 Runbooks 和事故模板。
5. 完成威胁模型、网络隔离、密钥、权限和 Web 安全。
6. 完成 SBOM、SAST、依赖、容器、许可证和秘密扫描。
7. 建立 Docker Compose 生产 Profile 和 systemd/进程管理。
8. 建立数据库迁移、备份、离机加密和恢复演练。
9. 建立 CI/CD、签名工件、审批和回滚。
10. 建立时间同步、磁盘和资源预警。
11. 执行渗透式安全测试和故障演练。
12. 生成 Paper/Testnet 部署手册，不启用 Live。

### 验收

- 关键事件可在指标、日志和追踪中关联。
- Promtail 未被使用。
- SEV0/SEV1 告警实际到达用户配置渠道。
- 从备份恢复成功并通过账本/对账验证。
- 研究环境无法读取实盘秘密。
- Dashboard 默认仅私网/localhost，可验证认证和 CSP。
- 发布可回滚，错误版本不会自动恢复交易。

---

## P17：付费数据源 Bake-off 与采购决策

### 目标

只在系统已有可靠免费基线后，用小范围试用证明某个付费数据源是否值得长期接入。

### 任务

1. 生成最小试用数据需求和预算。
2. Tardis vs Kaiko 比较；可以选择一家、都不选或延后。
3. CoinGlass 衍生品聚合评估。
4. CryptoQuant vs Glassnode 比较；可以选择一家、都不选或延后。
5. Databento 仅在跨资产/CME 假设存在时评估。
6. 新闻数据进行两档 Bake-off：Benzinga/Event Registry/CryptoPanic 中最多选一个个人级候选；RavenPack/Bigdata.com 或 LSEG MRN 中最多选一个机构级试用候选，用户预算不允许时可全部拒绝。
7. 评估 X API 查询/流式用量、历史回放覆盖和成本上限；不得因沉没成本强行保留。
8. 建立许可、历史覆盖、首发延迟、修订/删除、缺口、语言、价格和运维评分。
9. 与官方数据交叉核验。
10. 在相同研究预算下做 Baseline vs Baseline+Source 消融。
11. 对新闻源额外比较事件 recall、false alert、lead time、转载重复率和风险覆盖价值。
12. 分析 feature importance 之外的真实净交易增量。
13. 分析 Provider 停止服务时的降级。
14. 输出采购或拒绝建议，不以“已有试用”作为购买理由。
15. 只有批准的数据源进入 Provider Registry `approved`。

### 外部输入

用户可协助开通试用，但密钥只配置在本地秘密库。用户不愿付费时，阶段可以以“无充分证据，不采购”通过。

### 验收

- 选择基于 OOS、成本、许可和运维，不基于营销材料。
- 同类首期最多保留一家长期主源。
- 负结果完整保留。
- 未购买的 Provider 不成为系统硬依赖。
- 任何第三方聚合不替代官方交易事实。

---

## P18：Canary 实盘就绪审查与持续运营

### 目标

决定系统是否具备极小资金 Canary 条件；本阶段本身**不自动启用实盘**。

### 任务

1. 汇总 P00-P17 需求可追踪矩阵和未关闭风险。
2. 选择最多一个策略、一个账户范围和少量高流动性合约作为 Canary 候选。
3. 冻结模型、策略、风险、执行和数据依赖版本。
4. 形成 Canary Release Manifest、签名和到期时间。
5. 验证专用子账户、低余额、无提现、IP 白名单和最小权限。
6. 验证 Paper/Shadow/Testnet 的持续期、成交数和故障证据。
7. 验证风险限额、kill switch、告警和人工值守。
8. 执行预生产回放、启动对账和恢复演练。
9. 定义资本阶梯、停止条件、最大持续时间和评估窗口。
10. 定义真实成交相对模拟的监控和退回规则。
11. 进行独立 Go/No-Go 审查。
12. 生成用户需要人工确认的清单。
13. 默认输出 `NO_GO`，除非所有硬条件都有证据；即使 `GO`，仍保持 Live lock，等待用户单独、明确地执行解锁流程。
14. 建立持续运营制度：每日、每周、每月、季度检查。

### 必需报告

```text
reports/live_readiness/CANARY_RELEASE_MANIFEST.json
reports/live_readiness/GO_NO_GO.md
reports/live_readiness/OPEN_RISKS.md
reports/live_readiness/USER_APPROVAL_CHECKLIST.md
reports/live_readiness/CAPITAL_LADDER.yaml
reports/live_readiness/STOP_CONDITIONS.yaml
reports/live_readiness/ROLLBACK_PLAN.md
```

### 验收

- 所有关键需求可追溯到代码、测试和运行证据。
- 无未解释账本或对账差异。
- 无未处理 SEV0/SEV1。
- 风险和执行 mutation/chaos 测试达标。
- Live 密钥不存在于研究和 CI。
- Canary 规模受到硬代码/政策双重上限。
- 人工不解锁时绝不产生真实订单。

---

# 24. 阶段外的持续运营制度

## 24.1 每日

- 数据质量和缺口；
- 账户、订单、成交、仓位和账本对账；
- PnL、费用、资金费率和滑点；
- 风险状态和事故；
- 模型新鲜度和漂移；
- 交易所公告和规则变化；
- 备份状态。

## 24.2 每周

- 策略/模型 live vs expected；
- 执行质量；
- 风险预算；
- 数据源健康；
- 失败实验和新假设；
- 依赖/安全变更；
- 容量和成本曲线。

## 24.3 每月

- 组合归因；
- 模型校准；
- 策略相关和重复；
- 参数与状态稳定；
- 压力测试；
- 事故复盘；
- 数据和云成本；
- 恢复演练抽查。

## 24.4 每季度

- 全依赖升级评估；
- 交易所 API 契约回归；
- 权限和密钥轮换；
- Provider 采购复审；
- 模型/策略再验证；
- 威胁模型更新；
- 灾备恢复演练；
- Live 资本上限重新批准。


---

# 25. 用户可协助接入的内容与请求时机

Codex 不得一次性要求全部账号。它应在相应阶段生成精确、最小化的请求。用户提供的是路径、权限状态或在本机配置完成的秘密名称，不是在聊天或 Markdown 中提供秘密值。

## 25.1 P00/P02：最高优先级

请求：

1. 用户原始数据只读路径；
2. 历史回测/实验结果只读路径；
3. 旧策略源码只读路径；
4. `R331` 是否存在及其路径；
5. 可用于项目的数据磁盘空间；
6. Windows/WSL/Docker/GPU 使用偏好；
7. 用户可接受的研究云费用上限；
8. 用户的交易地域、账户和产品权限说明；
9. 是否愿意申请 X Developer 项目及可接受的月度用量上限；
10. 是否有专用 Telegram 研究账号、需要监控的公开/获授权频道 allowlist；
11. 是否可创建 YouTube API、GitHub App/Token 等只读访问；
12. 风险偏好问卷，但未确认前不用于 Live。

禁止请求：

- 私钥；
- 交易所 Secret 明文；
- 浏览器 Cookie；
- 短信验证码；
- 聚宽密码；
- 任何提现凭据。

## 25.2 P09：知识平台

可以请求：

- 聚宽账号是否能正常由用户本人登录；
- 能否查看正文、源码、评论和附件；
- JQData 权限和调用额度；
- 用户手工导出的资料包；
- 米筐、BigQuant、知识星球等合法导出；
- 用户认为重要的失败复盘。

推荐用户优先收集：

- 完整规则和源码；
- 回测成交明细；
- 费用/滑点；
- 样本外和实盘差异；
- 作者后续修正；
- 评论中的未来函数和失效讨论。

## 25.3 P04/P10：新闻、推文、频道和免费/低门槛数据

可请求用户在本地秘密库配置或完成人工授权：

- X Developer 项目、Bearer/OAuth 只读凭据和用户已批准 use case；
- X 查询关键词、cashtag、列表和官方/专家账号 allowlist；
- 可接受的 X 月度预算、硬停止金额和历史检索范围；
- Telegram API ID/Hash 或 Bot Token 的本地 secret reference；
- Telegram 专用研究账号由用户本人完成登录，提供频道 allowlist，不提供短信验证码或 session 文件；
- YouTube Data API key；
- GitHub App/Token，只给所需公开/只读权限；
- FRED API key；
- Dune API key；
- Event Registry/CryptoPanic/Benzinga 等试用 Key，仅在已有试验计划时；
- 其他需要注册的免费 API。

公开接口不需要 Key 时，不应要求用户创建账户。所有凭据只保存在本地秘密库，任务书和聊天中只记录 secret reference 名称。Reddit、Discord、微博、TikTok 在未通过用途和条款审查前不请求凭据。

## 25.4 P12：Testnet

请求：

- Binance Testnet 或等价沙盒凭据已在本地秘密库配置；
- 账户模式、子账户、持仓模式和权限；
- 不提供明文值，只提供 secret reference 是否存在。

## 25.5 P17：付费试用

按顺序请求：

1. Tardis 或 Kaiko 小范围试用，优先一个；
2. CoinGlass；
3. CryptoQuant 或 Glassnode，优先一个；
4. Databento，仅当已有跨资产假设；
5. Benzinga/Event Registry/CryptoPanic 中最多一个个人级新闻试用；
6. RavenPack/Bigdata.com 或 LSEG MRN 中最多一个机构级试用，预算不适合时跳过。

Codex 必须先提供：预期数据范围、试验假设、预计调用/存储、最长试用时间、成功/失败标准和停止条件。没有此说明，用户不应购买。

## 25.6 P18：Canary

只有在 `GO_NO_GO.md` 具备证据后，才向用户请求：

- 是否愿意建立专用低余额子账户；
- 确认风险上限；
- 确认运行和告警时间；
- 确认 Canary 资产和停止条件；
- 在本机秘密库配置无提现、IP 白名单的 API；
- 单次人工解锁。

用户不确认时，项目保持完整的 Paper/Shadow 系统，不视为工程失败。

---

# 26. 项目完成定义

## 26.1 研究平台完成

以下全部满足：

- 数据湖、Provider Registry、PIT 和质量体系可用；
- Binance 及多交易所公共数据可采集和回放；
- 特征、标签、实验、Model Council 和严格验证可用；
- 所有实验可复现且保留失败记录；
- 聚宽/外部资料可合规导入、静态分析、结构化和迁移；
- 至少有简单基线和若干候选策略，但不要求它们一定盈利。

## 26.2 Paper/Shadow 交易平台完成

以下全部满足：

- 双重账本和 PnL 正确；
- event backtest、Paper、Shadow 语义一致；
- 独立组合和风险引擎；
- 订单状态机、Testnet、对账和恢复；
- 故障和长时间运行测试；
- 完整 Web 看板；
- 可观测性、安全、备份和部署。

这是项目的主要生产级完成点。

## 26.3 Canary 就绪

只有 P18 通过独立 Go/No-Go，且用户随后明确解锁，才称为 Canary 就绪。Canary 交易结果不构成未来盈利保证。

## 26.4 不以以下事项作为完成证据

- 某条高收益回测曲线；
- AI 生成的策略数量；
- GitHub Star；
- 模型参数规模；
- 已购买昂贵数据；
- 界面截图；
- Testnet 盈利；
- 未计成本的预测准确率；
- 没有逐笔成交和账本的收益汇总。

---

# 27. Codex 第一轮直接执行指令

将本文件放入清空后的项目根目录，向 Codex 提交以下指令：

```text
完整读取《AegisQuant v3.1：个人 AI 加密资产多模态市场情报、预测、交易与可视化系统——Codex 从零实施总任务书》，将它视为本项目唯一且最高优先级的工程规格。

当前项目目录为空，不得假定旧版 AegisQuant、JQ-0、数据库、代码或报告仍存在。请只执行 Phase P00：项目启动、规格固化与安全基线。

执行前先建立需求可追踪矩阵和 P00 实施计划；执行后运行所有规定测试，生成 P00 的 PLAN、SUMMARY、TEST_RESULTS、ACCEPTANCE、RISKS、NEXT_ACTIONS、ARTIFACT_MANIFEST 和 ADR_REFERENCES，并更新 PROJECT_PHASE_STATE.yaml。

必须保持 LIVE_TRADING 锁定；不得连接真实交易账户；不得索取或写入任何明文密码、Cookie、验证码或 API Secret；不得使用占位实现；不得开始 P01。若外部版本或兼容性与任务书不同，以官方稳定文档和实际契约测试为准，写入 ADR。
```

Codex 后续每轮通用指令：

```text
读取总任务书、PROJECT_PHASE_STATE.yaml、当前阶段所有报告和未关闭风险。只执行 state 中 current_phase 指定的阶段。先计划，后实现，运行完整测试并生成强制报告。验收不通过则标记 failed/blocked 并停止，不得进入下一阶段。不得降低安全、point-in-time、账本、风险、对账和实盘锁要求。
```

---

# 28. 官方资料与工程参考索引

> 访问日期：2026-08-31。版本可能继续变化，P00 必须重新读取官方稳定版本并锁定。以下链接用于技术选择、契约和设计参考，不代表任何第三方为本项目收益背书。

## 28.1 核心交易与研究框架

- NautilusTrader 文档：https://nautilustrader.io/docs/
- NautilusTrader Integrations：https://nautilustrader.io/docs/latest/integrations/
- QuantConnect LEAN：https://www.lean.io/
- Microsoft Qlib：https://github.com/microsoft/qlib
- VeighNa：https://www.vnpy.com/
- Hummingbot：https://hummingbot.org/
- Freqtrade / FreqUI：https://www.freqtrade.io/
- OpenBB Workspace：https://docs.openbb.co/workspace

## 28.2 Python、Web 与可视化

- Python：https://www.python.org/downloads/
- uv：https://docs.astral.sh/uv/
- PyTorch：https://pytorch.org/
- FastAPI：https://fastapi.tiangolo.com/
- Node.js：https://nodejs.org/en/about/previous-releases
- Next.js：https://nextjs.org/docs
- React：https://react.dev/
- shadcn/ui：https://ui.shadcn.com/
- Tailwind CSS：https://tailwindcss.com/docs
- Apache ECharts：https://echarts.apache.org/
- TradingView Lightweight Charts：https://tradingview.github.io/lightweight-charts/
- TanStack Query：https://tanstack.com/query/latest
- TanStack Table：https://tanstack.com/table/latest
- Playwright：https://playwright.dev/

## 28.3 数据与存储

- Polars：https://docs.pola.rs/
- Apache Arrow：https://arrow.apache.org/docs/
- DuckDB：https://duckdb.org/docs/stable/
- PostgreSQL：https://www.postgresql.org/docs/
- TimescaleDB：https://docs.timescale.com/
- MLflow：https://mlflow.org/docs/latest/
- Optuna：https://optuna.readthedocs.io/

## 28.4 交易所官方接口

- Binance Developers：https://developers.binance.com/
- Binance Spot WebSocket Streams：https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams
- Binance USDⓈ-M Futures：https://developers.binance.com/docs/derivatives/usds-margined-futures/
- OKX API：https://www.okx.com/docs-v5/en/
- Bybit API：https://bybit-exchange.github.io/docs/v5/intro
- Deribit API：https://docs.deribit.com/

## 28.5 宏观、链上与 DeFi

- FRED API：https://fred.stlouisfed.org/docs/api/fred/
- ALFRED：https://alfred.stlouisfed.org/
- Coin Metrics API：https://docs.coinmetrics.io/api/v4/
- Dune API：https://docs.dune.com/api-reference/overview/introduction
- DeFiLlama：https://defillama.com/
- GDELT：https://www.gdeltproject.org/

## 28.5A 全球新闻、社交与开发事件

- X API 总览：https://docs.x.com/x-api/introduction
- X API Rate Limits：https://docs.x.com/x-api/fundamentals/rate-limits
- X API Pricing/Usage：https://docs.x.com/x-api/getting-started/pricing
- X Developer Agreement：https://docs.x.com/developer-terms/agreement
- X Developer Policy：https://docs.x.com/developer-terms/policy
- Telegram Bot API：https://core.telegram.org/bots/api
- Telegram MTProto API：https://core.telegram.org/api
- Telegram Takeout API：https://core.telegram.org/api/takeout
- Bluesky Firehose：https://docs.bsky.app/docs/advanced-guides/firehose
- Bluesky Jetstream：https://docs.bsky.app/blog/jetstream
- YouTube Data API：https://developers.google.com/youtube/v3
- YouTube Live Chat：https://developers.google.com/youtube/v3/live/docs/liveChatMessages
- GitHub Webhooks：https://docs.github.com/en/webhooks
- Reddit Data API Terms：https://redditinc.com/policies/data-api-terms
- Discord Developer Policy：https://support-dev.discord.com/hc/en-us/articles/8563934450327-Discord-Developer-Policy
- CryptoPanic API：https://cryptopanic.com/developers/api/
- Benzinga APIs：https://docs.benzinga.com/
- Event Registry：https://eventregistry.org/
- RavenPack News Analytics：https://www.ravenpack.com/products/edge/data/news-analytics

## 28.6 付费数据候选

- Tardis.dev：https://docs.tardis.dev/
- Kaiko：https://docs.kaiko.com/
- CoinGlass：https://docs.coinglass.com/
- CryptoQuant：https://userguide.cryptoquant.com/cryptoquant-metrics/api
- Glassnode：https://docs.glassnode.com/
- Databento：https://databento.com/docs

## 28.7 时序基础模型候选

- Chronos：https://github.com/amazon-science/chronos-forecasting
- TimesFM：https://github.com/google-research/timesfm
- Moirai：https://github.com/SalesforceAIResearch/uni2ts
- Kronos：https://github.com/shiyu-coder/Kronos

## 28.8 可观测性和安全

- Grafana：https://grafana.com/docs/grafana/latest/
- Grafana Alloy：https://grafana.com/docs/alloy/latest/
- Prometheus：https://prometheus.io/docs/
- Alertmanager：https://prometheus.io/docs/alerting/latest/alertmanager/
- Loki：https://grafana.com/docs/loki/latest/
- OpenTelemetry Python：https://opentelemetry.io/docs/languages/python/
- OWASP ASVS：https://owasp.org/www-project-application-security-verification-standard/
- OWASP Cheat Sheet Series：https://cheatsheetseries.owasp.org/

---

# 29. 最终不可妥协清单

在任何阶段、任何实现或任何 AI 建议中，以下条款优先：

1. 不承诺盈利，不把预测当确定事实。
2. 先正确性、账本、风险和对账，后收益优化。
3. 研究与交易权限隔离。
4. AI 不持有密钥、不直接下单、不修改风险。
5. 所有数据有 `available_time` 和可追溯版本。
6. 所有实验包括失败试验，不能只保留最佳结果。
7. 简单基线永久存在，复杂模型必须证明增量。
8. 回测必须包括真实成本、成交、资金费率、保证金和故障。
9. 交易所官方接口是交易事实和规则的权威来源。
10. 未知订单状态先对账，不盲目重发。
11. 双重记账是 PnL 权威来源。
12. 风险引擎独立且不可绕过。
13. Web 主看板默认只读，不成为第二个不受控交易入口。
14. 外部平台内容按权限和许可获取，不绕过访问限制。
15. 系统不得只依赖 K 线；新闻、公告、推文和事件是第一等数据，但任何单一消息都不能直接下单。
16. 所有 AI 事件判断必须有证据、来源政策、冲突和不确定性；无证据即 abstain。
17. 社交内容的互动、编辑、删除和身份状态必须按历史快照处理，禁止未来泄漏。
18. 付费数据必须先试用、消融和证明价值。
19. 预发布依赖不进入实盘核心路径。
20. 首版不因架构炫技引入 Kubernetes、Kafka 或无必要微服务。
21. 所有关键状态都能重放、审计、恢复和停机。
22. 用户未明确解锁，系统永远不发送真实订单。
23. 任何漂亮结果都必须能由数据、代码、配置、种子、成交和账本完整复现。

---

**文档结束。**
