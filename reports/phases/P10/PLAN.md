# P10 实施计划

## 目标与边界

P10 在 P02 的不可变数据与来源政策、P04 的公共情报采集契约、P06/P07 的时点一致回测与
严格验证、P08 的 Proposal-only AI 边界以及 P09 的外部知识安全门禁之上，建立全球多源事件
智能、证据图、叙事状态、事件影响融合预测和事件回放能力。

本阶段接入契约覆盖 FRED/ALFRED、Coin Metrics Community、Dune、DeFiLlama、官方交易所/
项目方/监管机构/法院/央行/ETF 发行人、GDELT，以及经用户许可的 X、Telegram、Bluesky、
YouTube、GitHub。无需凭据的公开契约可使用本地夹具和可复现请求验证；需要凭据的来源在本地
秘密引用未配置时必须保持 `AWAITING_CREDENTIALS`，不得要求用户在聊天中粘贴 API Secret、
密码、Cookie、验证码或会话凭据，也不得伪称已完成生产采集。

事件管线保存原文、规范化文本、可审计翻译、修订/删除版本、互动快照、近重复与转发家族、
跨平台实体、Claim、支持/反驳关系、EventCluster、NarrativeState 和状态机。Fast/Deep 路径均
强制包含 Skeptic 检查与结构化弃权；LLM 只能产生证据绑定的分析 Proposal，不能生成
`OrderCommand`，单条社交帖子不能直接触发订单。事件影响预测必须与价格、订单簿、OI、资金费率、
基差及链上特征进行时点一致融合，并以相同预算报告 Market-only、Event-only、Fused、Risk-only
四视角结果，包括负结果。

项目业主要求全部工程完成后统一正式验收。依据 ADR-0010，P10 完成实现和规定测试后保持
`in_progress`，不生成 `ACCEPTANCE.md`，不写 `accepted_at_utc`。始终保持
`LIVE_TRADING=false`、`live_trading_locked=true`；不连接真实交易账户，不请求或保存任何明文
秘密，不开始 P11。

## 实施顺序

1. 建立 P10 需求可追踪矩阵，固化全球来源、权利、版本、时点、Jetstream v2 与事件回放 ADR。
2. 实现 FRED/ALFRED vintage、Coin Metrics Community、Dune 查询注册表/SQL 版本/结果清单、
   DeFiLlama 与官方来源目录的严格请求及响应契约。
3. 实现 GDELT 发现到原始来源追踪，并为 X、Telegram、Bluesky、YouTube、GitHub 建立只读、
   配额、缺口、回填、游标、退避和凭据缺失降级状态；仅启用用户许可来源。
4. 实现来源权利矩阵，明确本地存储、云推理、嵌入、训练/微调、展示、导出、删除同步与保留期；
   未知权利默认关闭敏感用途。
5. 实现多语种规范化、原文保留、翻译审计、近重复、转发家族和跨平台实体链接；翻译只接收带
   模型/版本/置信度/输入输出哈希的已批准结果，不伪造通用翻译器。
6. 实现事件本体、Claim 支持/反驳、证据图、EventCluster、NarrativeState、事件状态机、来源身份/
   域准确度/更正/官方性/操纵风险/独立性评分。
7. 复用 P08 委员会实现 Fast/Deep 路径，强制 Skeptic、证据覆盖、冲突记录与结构化弃权；保持
   Proposal-only 边界。
8. 实现多资产、多时域 EventImpactForecast，与价格、订单簿、OI、资金费率、基差和链上数据进行
   point-in-time 融合，并执行同预算四视角消融。
9. 实现修订、删除、互动快照、延迟压力、未来互动泄露、趋势前置和安慰剂检查的事件回放；所有
   `as_of` 选择只允许读取当时已可用版本。
10. 实现人工标注、主动学习队列、本体版本，以及 Event Radar、Evidence Graph、Narrative Monitor、
    Source Monitor、Event Replay 五个确定性只读模型。
11. 实现无增量来源的监控/保留/退役建议；风险视角允许保留，但不得包装成正向 Alpha。
12. 运行 P10 定向测试、全量 pytest、Ruff、Pyright、Python 3.14 契约、mutation、安全/秘密/
    依赖/许可证扫描、前端测试与构建。
13. 生成延期验收口径的 SUMMARY、TEST_RESULTS、RISKS、NEXT_ACTIONS、ARTIFACT_MANIFEST、
    ADR_REFERENCES，更新阶段状态并执行一次本地 Git 归档。

## 验证标准

- ALFRED 同一观察值可按不同 vintage 重放，回放不会看到未来修订。
- Dune 请求记录查询 ID、SQL 版本/哈希、参数、execution ID、结果哈希和可用时间，可复现结果来源。
- 内容更新、删除及互动快照保留首版和完整版本链；回放只选择 `available_at <= as_of` 的版本。
- 每个高影响事件簇可追溯证据、来源政策、模型版本、冲突和结构化弃权原因。
- 100 条同源转发最多计为一个独立来源家族；来源独立性不得被热度或重复数量虚增。
- 四视角在相同数据窗、计算预算、成本与验证规则下报告 OOS 正负结果，不挑选好看的单一结果。
- 5 秒、30 秒、2 分钟、10 分钟等延迟压力与未来互动泄露检查真实改变可用信息边界。
- 来源或 LLM 不可用时明确降级，不能隐式切换到更宽权限、未来数据或不可审计输出。
- 未知权利、Reddit、Discord 默认禁用；单条社交帖子和 LLM 输出均不能生成订单。
- `LIVE_TRADING` 始终锁定，所有测试仅使用项目自有确定性夹具或显式公开只读契约。

## 明确非目标

- 不请求、保存或回显密码、Cookie、验证码、会话令牌或 API Secret；不连接真实交易账户。
- 不绕过付费墙、登录、地区限制、robots、平台配额或内容删除；不抓取未获用户许可的私域来源。
- 不把本地夹具测试写成“生产源已上线”，不把匿名转发数量当独立证据，不把翻译结果当原文。
- 不执行外部网页、SQL、Notebook 或代码；Dune 只允许登记并调用用户批准的只读查询契约。
- 不使用未来修订、未来互动、未来删除状态或回填到达时间；不以零延迟假设美化结果。
- 不让事件模型绕过 P05/P08 风控与执行边界，不生成真实订单，不开始 P11，不做正式阶段验收。
