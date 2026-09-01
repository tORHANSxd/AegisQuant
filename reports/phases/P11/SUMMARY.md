# P11 实施总结

P11 已完成信号归一化、组合构建、独立风险快照与决策、预交易门禁、单向安全状态机、签名风险政策、
重大事件剧本和压力回放。正式验收按项目业主决定统一后置；阶段保持 `in_progress`，不生成
`ACCEPTANCE.md`，不写入 `accepted_at_utc`，`LIVE_TRADING` 继续锁定。

## 已交付

- 置信度与不确定性折扣、no-trade zone、shrinkage/因子/状态协方差、逆波动风险预算、波动目标与
  仅收缩的稳健优化器。
- 资产、合约、策略、sleeve、venue、稳定币和相关簇七维暴露约束，以及 turnover、impact 和
  capacity 硬约束；每个 `PortfolioProposal` 保留贡献与约束理由且不具备下单能力。
- 独立生成并内容寻址的 `RiskSnapshot`、签名且带版本与时效的 Paper-only `RiskPolicy`、不可放大
  `PortfolioProposal` 的 `RiskDecision`，以及订单/资产/策略/账户四层预交易限额。
- `NORMAL`、`CAUTION`、`REDUCE_ONLY`、`HALTED`、`RECOVERY` 五态风险机；自动迁移只能更安全，
  恢复必须由非 AI 操作者满足八项前置条件。
- 数据、模型、损失、保证金、流动性、交易所、安全和重大事件八类熔断器，以及官方安全事件、
  提现暂停、稳定币脱锚、重大监管、基础设施中断五类签名剧本。
- 谣言路径只能监控、收紧或有上限减仓，LLM 与研究/模型进程均没有风险覆盖或全量清仓能力；
  Kill Switch 和 Reduce-only 行为可确定性回放。

## 生产状态与边界

风险数值、签名和市场数据均为项目自有确定性夹具，只验证工程契约，不构成生产校准、Alpha、盈利或
Live 批准。夹具私钥只在测试进程内派生，仓库仅保存公开验证材料；没有访问秘密存储，没有连接真实
交易账户，没有创建交易所订单命令，也没有外部副作用。

## 验证状态

完整 CI 35/35 阶段通过；Python 3.13 全量测试 481/481、Python 3.14.7 隔离候选契约 444/444
通过，严格 Pyright 与 Ruff 均为 0 问题。11/11 关键变异全部被杀死。Bandit finding 为 0，Secret
命中为 0，Python/JavaScript 依赖审计、SBOM 与许可证清单通过，Python 未知许可证计数为 0；前端
lint、类型检查、单测、生产构建与 Playwright E2E 全部通过。

证据收口期间保留了两次非产品缺陷预跑：秘密扫描曾把确定性 `idempotency_key` 内容哈希判为高熵
秘密；首遍完整 CI 的 Bandit 又把 `secret_store_access_performed=false` 审计字段判为硬编码密码。
前者使用精确内容寻址字段排除，后者改为类型化布尔常量；两者均完整重跑为 0，原始失败与处置记录
在 `TEST_RESULTS.json`，没有拿误报当真漏洞，也没有把失败藏掉。

实现提交为 `7744354c993334a572a4e4e5a61e53eabc62453f`。最终流水线、测试统计与工件哈希分别见
`CI_RESULTS.json`、`TEST_RESULTS.json` 和 `ARTIFACT_MANIFEST.json`。
