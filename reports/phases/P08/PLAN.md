# P08 实施计划

## 目标与边界

P08 在 P04 的事件来源与证据契约、P07 的 point-in-time 数据集、时间验证、最终 holdout 锁和
追加式实验账本之上，建立可审计研究工厂、Model Council、模型注册与安全 AI 研究代理。

本阶段交付 MLflow/Optuna 研究控制面、Hypothesis/Experiment/Event Proposal 门禁、三类树模型、
两个轻量深度时序模型、四类基础模型插件、预测分布与校准、OOF stacking、状态门控、drift/OOD、
Champion/Challenger、Model Card、Event Expert Committee、证据图和一次历史事件回放。

项目业主要求全部工程完成后统一正式验收。依据 ADR-0010，P08 完成实现和规定测试后仍保持
`in_progress`，不生成 `ACCEPTANCE.md`，不写 `accepted_at_utc`。当前主机没有 NVIDIA GPU，
4070 Ti 实机资源测试留待统一验收；本阶段必须完成 CPU 路径、资源拒绝和可恢复 OOM 契约。

配置保持 `LIVE_TRADING=false`、状态保持 `live_trading_locked=true`。研究代码、LLM、事件代理和
模型注册均无执行服务、真实账户或交易秘密能力；最终 holdout 保持 `LOCKED`，本轮不启动 P09。

## 实施顺序

1. 固化 P08 需求追踪、阶段状态、依赖/模型许可/硬件/研究治理 ADR。
2. 锁定 MLflow、Optuna、LightGBM、CatBoost、XGBoost、PyTorch 和有限基础模型依赖，执行
   Python 3.13/3.14 解析、导入、训练与序列化契约。
3. 实现机器可读 Hypothesis Spec、Proposal 审批、持久化队列、资源/搜索/调用/成本预算和
   失败关闭的 experiment launcher。
4. 扩展追加式实验账本，接入本地 loopback MLflow、Optuna JournalStorage 和内容寻址
   Artifact Registry；保留开始、成功、失败、异常、剪枝、超时和恢复事件。
5. 实现统一概率预测接口以及 LightGBM、CatBoost、XGBoost、轻量 TCN 和轻量 Patch
   Transformer，固定种子、线程、数据切分和资源上限。
6. 实现 Chronos-2、Moirai 2、TimesFM 3、Kronos 插件契约。不可用插件必须给出许可、硬件、
   依赖或权重原因，不允许静默冒充基线；有限 CPU 评测优先使用许可允许的小型 Chronos-2。
7. 实现分位数预测、残差分布、split conformal 区间、校准评估和低 edge、高不确定性、高分歧、
   数据陈旧、成本过高、OOD、风险限制七类 abstain。
8. 实现严格 OOF stacking、权重上限与平滑、point-in-time 状态门控和输入/缺失/预测/残差/
   校准/延迟基础漂移与 OOD 监控。
9. 实现 Model Card、研究级 Champion/Challenger alias 和显式晋升 Proposal；自动训练和 AI
   不得改 alias、发布模型或打开最终 holdout。
10. 实现供应商无关结构化 LLM Provider、RAG 内容隔离、Source Policy Gate、Unicode/长度/
    提示词注入防火墙和 JSON Schema/evidence coverage 校验。
11. 实现 Extractor、Entity、Source、Corroboration、Skeptic、Market、On-chain、Impact、Policy
    和 Arbiter 委员会，以及 Claim/Event Graph、冲突、来源家族、状态迁移和多时间尺度影响预测。
12. 运行一次完整 Model Council。所有可比候选使用相同开发期 OOS split、成本、搜索预算和种子；
    不适用专家结构化 abstain，失败和负结果保留，最终 holdout 不开启。
13. 使用具有精确发布时间的一手宏观事件和校验和固定的公共加密市场数据运行一次历史回放，
    验证首次可得时间、延迟、冲突、证据覆盖和 Market/Event/Fused 比较，不声称历史因果或 Alpha。
14. 运行单元、属性、契约、集成、回放、性能、提示词安全、mutation、双运行时、SBOM、许可证、
    依赖漏洞、secret scanning 和完整 CI 门禁。
15. 生成延期验收口径的 SUMMARY、TEST_RESULTS、RISKS、NEXT_ACTIONS、ARTIFACT_MANIFEST、
    ADR_REFERENCES、机器证据和全局状态，并执行一次本地 Git 归档。

## 验证标准

- AI 生成或外部输入的无效 schema 在创建 experiment、trial 或 MLflow run 前被拒绝。
- 每个 trial 和 run 的开始与终态均可追溯；失败、异常、剪枝和负结果不可删除。
- 树、深度、基础模型和基线使用相同 split、成本、预算、指标与种子报告，复杂模型没有类别特权。
- 所有 OOF 样本只由未见过该样本的折生成；stacking 权重有上限、平滑和防短期追涨约束。
- 预测区间有序且有限；低置信度、高分歧、陈旧、成本、OOD 和风险限制能确定性 abstain。
- 外部文本只能作为 untrusted data，不能获得工具、配置、秘密、账户、订单或执行能力。
- Arbiter 只能组合已提供的 Evidence ID；无证据事实失败关闭，冲突和缺失证据必须保留。
- 基础模型记录代码/权重来源、revision、许可证和 SHA-256；受限权重不能进入生产用途。
- CPU 预算和模拟 OOM 恢复测试通过；未在 4070 Ti 实测前不得宣称该项正式验收通过。
- 最终 holdout loader 调用次数保持 0，`LIVE_TRADING` 保持锁定，未出现明文秘密。

## 明确非目标

- 不实现 P09 的聚宽/外部知识导入与通用源码静态分析系统。
- 不实现 P10 的完整宏观、链上、DeFi 和全球来源生产接入。
- 不实现组合、风险、执行、Paper、Shadow、Testnet、Canary 或实盘路径。
- 不连接云 LLM、真实交易账户或需要秘密的外部服务；契约测试使用注入 transport。
- 不运行 12/24 小时 soak，不生成正式 ACCEPTANCE，不用合成结果冒充市场收益。
