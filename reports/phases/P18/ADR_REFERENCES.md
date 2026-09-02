# P18 ADR 引用

- `ADR-0023`：P18 逐项硬门、默认 `NO_GO`、空 Canary 范围、零有效资本、短期非授权 Manifest、停止
  条件、独立人工解锁和不执行 12h/24h 的直接决策。
- `ADR-0022`：P17 零采购与免费基线降级，确保未试用商业 Provider 不成为 Canary 运行依赖。
- `ADR-0021`：P16 可观测性、Secret 隔离、私网部署、签名、备份恢复和目标环境证据边界。
- `ADR-0018`：P13 Paper、Shadow、Chaos、语义一致性、对账与墙钟稳定性证据边界。
- `ADR-0017`：P12 Testnet-only、订单状态机、规则快照、幂等恢复和真实账户隔离。
- `ADR-0016`：P11 独立风险、硬限额、kill switch、不可旁路决策和风险状态单向安全原则。
- `ADR-0013`：P08 模型委员会、资源预算、最终 Holdout 与不夸大开发样本结论。
- `ADR-0012`：P07 point-in-time、OOF、成本后基线和最终 Holdout 锁定政策。
- `ADR-0010`：正式验收统一后置，工程实现验证不能伪装为 acceptance。
- `ADR-0003`：`LIVE_TRADING` 默认拒绝、失败安全和不可旁路锁定。
- `ADR-0001`：Python、Node、pnpm、PostgreSQL 与依赖版本政策。

P18 未引入需要外部版本偏差处理的新运行依赖。当前运行版本和契约均由锁文件、实际生成 Schema、
Python 3.13/3.14、PostgreSQL、Nautilus 与 Web 全链测试验证；未来若账户、交易所、Linux、告警或签名
服务的实际契约与任务书不同，必须优先复核官方稳定文档和真实契约测试，并通过新的 ADR 记录，不能
静默修改本 ADR 或把测试证据升级成 Live 授权。
