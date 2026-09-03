# V5-P12 风险台账

- `V5-RISK-004`：没有真实 V5 OOS、Paper、Shadow 或 Testnet Forward。处置：当前七门全部阻塞，
  `NO_PROMOTION / EXTEND_PAPER`。
- `V5-RISK-020`：P10 风险服务没有可验证签发收据。处置：P12 定义 TESTNET_ONLY 签名授权收据并
  绑定完整决策、风险快照、Testnet、告警和对账；当前真实收据缺失。
- `V5-RISK-021`：P11 wall-clock 与外部数据没有受保护时间戳。处置：P12 要求预提交 trust root、
  签名 Evidence 与 protected timestamp receipt；当前只有 DEVELOPMENT contract fixture。
- `V5-RISK-023`：真实 Binance Testnet、外部告警和对账证据均不存在。处置：保持外部输入阻塞，
  不读取凭据、不连接账户、不以 simulator 或 loopback 替代。
- `V5-RISK-024`：真实 attestor 身份、密钥托管、轮换、吊销与透明日志尚未建立。处置：fixture key
  仅做合同测试；生产 trust root 必须在运行前独立审批和保护。
- `V5-RISK-025`：24 小时、3 个订单、2 个成交是 DEVELOPMENT bootstrap，不是生产功效门槛。
  处置：在真实运行前完成容量与统计功效研究并预提交；观察后不得降低门槛。
- `V5-RISK-026`：P12 七门合同可能被误读为全局 Promotion Gate 已通过。处置：明确记录全局门未评估，
  Data、Economics、Statistics 与 Forward 仍阻塞，继续 `NO_PROMOTION`。
