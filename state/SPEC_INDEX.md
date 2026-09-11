# 当前任务、有效约束与证据索引

## 当前入口

- 当前任务方案：[AegisQuant_整改与验证方案_20260909.md](../AegisQuant_整改与验证方案_20260909.md)。
- SHA-256：`fad71d7906f5abab6f3fc3c64bbd4968c36b5a140e2e8da87e2ad2d361891040`；582 行，保留原字节。
- 最新交付快照：[最新结果与代码审阅包](../AegisQuant_最新结果与代码审阅包_20260911.md)。
- 当前状态：[ALPHA_V4_PROJECT_STATE.yaml](ALPHA_V4_PROJECT_STATE.yaml)。
- 用户已确认并完成旧材料删除；实际范围与恢复方法见[清理记录](LATEST_ONLY_CLEANUP_PLAN.md)。
- 只在 `main` 工作；索引调整不授权重跑已完成 generation、拟合新模型、读取最终留出或交易。

## 当前任务方案章节

| 起始行 | 内容 |
|---:|---|
| 7 | 版本、实读范围与证据边界 |
| 43 | 已证实问题与待验证假设 |
| 80 | 六个研究问题及处理 |
| 320 | 优先级与分批实施 |
| 336 | 所有批次共用的规则 |
| 346 | B0 证据及只读审计契约 |
| 358 | B1 G1 机制与时钟语义 |
| 370 | B2 PIT 数据与 future-mutation |
| 382 | B3 共同风险基准与归因 |
| 394 | B4 执行实证及成本语义 |
| 406 | B5 组合风险与资金桥接 |
| 418 | B6 ML、OOF 与 nested 协议 |
| 434 | B7 一次性最终留出和独立评审 |
| 540 | 外部数据缺口与禁止虚构的部分 |
| 555 | 删除、合并与复用建议 |

B0–B7 的工程契约和合成验证已经交付；最新状态从
[最终工程报告](../artifacts/alpha_v5/20260910_final_contract_v1/report.md)读取，
不把任务方案中的“下一批”当作自动重新执行授权。真实数据、收益研究、ML 拟合和最终留出仍受各自前置门槛约束。

## 继续生效的安全与晋级约束

删除旧任务书不放宽规则。当前方案 §3.2、保留的各 generation 完整配置及下列原 v4 约束继续有效；
摘要不能替代冻结配置中的全部门槛。语义相同而更严格的已生效规则继续保留，不得事后手工挑选或放宽。

- `LIVE_TRADING = false`、`ORDER_SUBMISSION_ENABLED = false`，实盘适配器注册表为空；生产 CASH，ML/纸面/实盘/订单均未获准入。不读取真实 API 私钥，不连接真实交易账户，不靠提高杠杆掩盖负期望。
- 工程准入要求相关单元、集成和性质测试通过；无同 K 线前视成交；支持场景 Vector/Event 经济结果一致；每根市场事件保留 MTM；reduce_only、OCO、强平和借币有回归；同输入、seed、commit 可复现。当前历史测试需要恢复资料，不能因此自动通过。
- 原 v4 经济门槛包括：1.0×与1.5×成本下聚合样本外复合净收益为正；2.0×成本不出现毁灭性亏损；折净收益中位数为正，盈利折比例至少60%；成本后 Sharpe≥0.8、Calmar≥0.5；最大回撤≤25%或显著低于同期 Buy & Hold；成本/毛利润≤40%，单折或单年利润贡献≤40%。当前方案更严格的同义门槛和至少30笔闭合交易等完整配置要求同时生效。
- 原统计门槛为 DSR≥0.95、PBO≤0.20，参数小幅变化方向稳定，匹配换手随机基线显著较差，结论不依赖单一牛市折。数据不足返回 `INSUFFICIENT_EVIDENCE` 或对应契约的 `INCONCLUSIVE`，不能自动通过、缩小比较族或追加试验直到显著。
- 低交易次数同时报告非年化折收益与 block-bootstrap 区间。费用分母、利润集中度窗口和不同成本模式不可混用；不可通过删掉最难门槛来制造晋级。
- ML 必须证明同风险、同执行、无 ML 基准之上的独立增量，并同时满足冻结的经济、统计、尾部及校准要求；AUC 改善或更高市场 beta 不能替代经济增量。
- 最终留出必须是至少连续十二个月、此前未使用的数据；候选、配置、门槛和比较族先冻结，独立授权后仅一次 claim。claim 在读取前持久化，loader 失败仍耗费 claim，不可通过改名、缓存、预览、重建 generation 或间接特征读取重用。
- 失败试验仍属于完整试验史。历史重建使用 `RECONSTRUCTED_BASELINE` 标记；不得把重建结果冒充原预测，不修改保存报告的原始哈希或复用旧 generation。

停止盈利参数优化的原 v4 条件继续生效：零成本旧信号仍稳定亏损；多折透明基线及1.5×成本下为负；
盈利集中于单一折、行情或孤立参数；ML 无独立增量；不优于匹配随机基线；依赖未实现借币、免费负现金、
缺失强平或漏掉中间 K 线；只靠杠杆转正；重复读取 holdout 后调参；成本恒等式不闭合；
交易太少且区间覆盖严重亏损。相应结论为 `NO_PROVEN_ALPHA`，不自动扩张搜索空间。

## 最新保留结果

- [R5 G1 固定开发诊断](../artifacts/alpha_v5/20260908_research_churn_v3/report.md)：五项 churn 门槛通过，但盈利季度6/14，预登记比较未通过 Holm；继续 `NO_PROVEN_ALPHA`。
- [B0–B7 工程契约](../artifacts/alpha_v5/20260910_final_contract_v1/report.md)：工程交付不等于完整研究验收。
- [保存模拟记录核验 v2](../artifacts/alpha_v5/20260910_saved_evidence_v2/report.md)：215 个运行、17 组，`VERIFIED_STORED_SIMULATION`；不代表真实执行验证。
- [近期冻结 R4 F3](../artifacts/current_system_recent/20260908_v3/report.md)：不属于 G1 近期业绩，不是最终留出。
- 最新报告、任务方案、审阅包和配置保留原字节；其中旧路径在清理后属于 Git 历史引用。部分重新核验需要恢复前代原始输入与源码快照。

## 历史规格身份，仅供恢复定位

下列文件已从工作树删除；原文位于
[清理前 Git 快照](https://github.com/tORHANSxd/AegisQuant/tree/8b6f80040f123a50faf1391710aeeeb1f2beb152)。
它们不再构成待执行阶段队列；先恢复再运行涉及其字节身份或旧状态的历史检查。

| 原文件 | SHA-256 |
|---|---|
| `AegisQuant_盈利导向重构任务书_v4.md` | `36e51644b2e3bb5d9570f8dcc18c4a7136f542e9f878b3b709739aa84eb9be85` |
| `AegisQuant_盈利验证修复任务书_R2_2026-09-08.md` | `15ad2e6541e9e5b29306a0ba5cdc60305f12f0ce0b137dfdcc4b610cabeabe49` |
| `AegisQuant_R4/AegisQuant_R4_低换手与连续持仓优化任务书_20260908.md` | `3304ba9a85efc46bc4534c379b5dceb5d6d098bd91c7ff0b8026dc89b4767b8f` |
| `deep-research-report.md` | `fbd6038da014075e68d88eaf6aa5ffdc8d435dcef4a1e04650942be2739ec5f6` |
| `AegisQuant_v5.0_Truth_Causal_AI_Forecast_Codex_Master_Plan.md` | `aee366d5fa1a8ebd7449c597e6f822535546633efc335c1ab0053333d160a255` |
| `AegisQuant_v3.1_Multimodal_Event_Intelligence_Codex_Master_Taskbook.md` 及其原副本 | `1265a4feeb126bf9004685b80c0aa01d053fd983079b80d5c9063abefc382d1f` |

历史 v3.1 为 7,023 行、P00–P18；历史工程 v5 为2,799行、V5-P00–V5-P12；
原 v4 为1,510行。当前 R5 研究 generation 与历史工程 v5 是不同身份。
