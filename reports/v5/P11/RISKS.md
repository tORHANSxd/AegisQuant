# V5-P11 风险台账

- `V5-RISK-004`：没有真实 V5 Paper/Shadow Forward。处置：真实观察日数记录为 0，输出
  `EXTEND_PAPER / NO_PROMOTION`；不得拿回测或 fixture 替代。
- `V5-RISK-016`：成本校准仍没有真实 realized TCA。处置：实现 predicted-vs-realized 成本指标与
  fail-closed 阈值，等待真实 Paper fill 样本持续累积。
- `V5-RISK-021`：wall-clock、外部数据和 incident attestation 目前只有结构与内容哈希，缺乏受保护
  时间戳或透明日志。处置：保持 DEVELOPMENT；P12 引入签名收据和外部告警证据。
- `V5-RISK-022`：独立事件样本门槛尚无真实 power study。处置：门槛必须预提交并带理由；样本不足
  只能延长 Paper，禁止事后下调。
