# P07 实施计划

## 目标与边界

P07 建立第一套完整、朴素、可信且可审计的研究基准：强类型 Feature Registry、不可变
Feature Snapshot、批/增量一致性、可交易标签、point-in-time Universe、严格时间验证、
反过拟合统计、简单策略与模型基线、公平消融、压力测试、最终 holdout 锁和基线排行榜。

P07 复用 P02 的 point-in-time join、P04 的事件 revision/互动快照、P05 的权威账本和 P06 的
成本与回测结果，不建立平行数据或收益口径。所有输入使用合成固定夹具或已归档公共数据；不连接
真实账户、不认证、不下单，`LIVE_TRADING` 始终锁定。

项目业主要求全部工程完成后统一验收。依据 ADR-0010，P07 完成实现与验证后仍保持
`in_progress`，不生成 `ACCEPTANCE.md`、不写 `accepted_at_utc`，也不在本轮进入 P08。

## 实施顺序

1. 固化 P07 需求追踪、阶段状态、依赖与统计方法 ADR。
2. 实现 Feature Definition、Registry、Snapshot、Feature Set Manifest 和批/增量 parity。
3. 实现收益、趋势、波动率、流动性、资金费率、基差、横截面和事件基础特征。
4. 实现净收益、三分类、分位数、波动率、MAE/MFE、执行和事件影响标签。
5. 实现 point-in-time Universe 与训练数据八类 Manifest 的失败关闭门禁。
6. 实现 walk-forward、purge、embargo、CPCV/CSCV、PBO、PSR/DSR 和多重试验修正。
7. 实现最终 holdout 冻结前不可读的一次性访问锁和追加式审计。
8. 实现现金、持有、趋势、横截面、carry/basis、官方事件风险覆盖和保守事件候选。
9. 实现线性、Logistic、Elastic Net、HAR-RV、简单状态模型及 Market/Event/Fused 公平比较。
10. 实现费用倍数、事件延迟、互动快照、参数扰动和 point-in-time 状态切片。
11. 实现追加式实验账本和 `BASELINE_SCOREBOARD.md`，保留失败、负结果、gross/net 和事件增量。
12. 运行 Golden、属性、泄漏注入、split、holdout、统计、模型、压力、mutation、静态、安全、
    许可证和双运行时门禁。
13. 生成延期验收口径的阶段报告、工件清单、提交绑定与本地归档。

## 验证标准

- 随机 shuffle 时间切分在 API 和架构测试中均被拒绝。
- 故意注入未来特征、未来标签、最终互动数和最终修订时，泄漏审计主动失败。
- 同一输入的批处理和增量特征在声明容差内一致。
- 简单策略净收益与独立手算 Golden Case 一致，gross 与 net 分列。
- 所有成功、失败和异常试验都可按 run ID 查询，差结果不能删除。
- PBO、PSR/DSR 和多重检验使用原始方法来源与独立数值夹具验证。
- 最终 holdout 在模型、参数、数据、成本与代码哈希冻结前不可读取。
- Market-only、Event-only、Fused 使用相同样本、切分、预算、成本和指标。
- 报告包含事件增量和负结果，不使用单一 Sharpe 排名。
- 关键反泄漏与 holdout mutation score 不低于 90%，所有随机过程固定并记录种子。

## 明确非目标

- 不实现 P08 的 MLflow、Optuna、Model Council、树模型、深度模型或 AI 研究代理。
- 不接入真实账户、私有 API、执行服务或任何密码、Cookie、验证码、API Secret。
- 不执行 12/24 小时 soak 或正式阶段验收。
- 未收到旧 R331 时不制造外部基准；HKUDS/AI-Trader 只作设计参考，不复制其代码。
