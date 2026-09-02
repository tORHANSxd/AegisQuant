# Margin Risk Runbook

## Detection and severity

- 保证金率、清算距离、集中度或压力损失突破策略硬限额，触发 `SEV0/SEV1`。
- 风险引擎独立决定 `REDUCE_ONLY` 或 `HALTED`，任何模型不得绕过。

## Immediate actions

1. 拒绝所有增加风险的 PortfolioProposal/OrderIntent。
2. 固化账户快照、价格来源、保证金规则版本、压力场景和风险决策签名。
3. 仅按预先批准 playbook 评估减仓；状态不明时先对账。

## Forbidden actions

- 禁止临时提高限额、忽略资金费率/流动性、由 LLM 自由全平或发送真实订单。
- 禁止使用过期价格或未验证场所规则。

## Evidence and recovery

- 保存风险前后快照、决策链、执行/成交/账本和对账证据。
- 风险指标回到限额内、数据新鲜、对账清晰且人工批准后，仍以原非 Live 模式恢复。
