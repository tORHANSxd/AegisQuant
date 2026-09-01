# P12 后续动作

1. 保持 `LIVE_TRADING=false`、`live_trading_locked=true`；不得添加 Live adapter、生产交易域名、
   提现能力或真实账户默认配置。
2. P12 证据固化后停止在阶段边界，不在本任务中启动 P13。
3. 若未来执行真实 Testnet 验收，只接受用户在本机秘密存储中预先配置的 credential reference 名称；
   不在对话、代码、配置、日志或报告中索取、读取或写入明文密码、Cookie、验证码、API Key/Secret。
4. 真实 Testnet 运行时按 `P12-A01` 单独收集提交、部分成交、撤单、断线重连、进程重启和账户对账
   证据；任何失败、限频、未知状态和恢复过程必须原样保留，模拟结果不得替代。
5. Nautilus 或交易所契约升级前先运行固定版本导入/字段/方法契约，并把文档差异与实际测试结果写入
   新 ADR；默认环境为 `None` 或 Live 时必须继续拒绝。
6. 正式统一验收由项目业主另行发起；届时再生成 `ACCEPTANCE.md` 并写真实 `accepted_at_utc`。
