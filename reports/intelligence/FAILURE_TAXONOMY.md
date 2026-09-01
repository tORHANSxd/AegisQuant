# Failure Taxonomy

| Tag | Meaning | Default action |
|---|---|---|
| INFORMATION_MISSING | 参数、规则或证据不完整 | 保持缺失，不允许 AI 补造 |
| LEAKAGE | 未来函数或 available-time 风险 | 拒绝 |
| SURVIVORSHIP_BIAS | 历史成分/可交易集合不可信 | 隔离并重建 PIT Universe |
| COST_SENSITIVE | 成本未给出或结果对成本脆弱 | 使用统一成本重跑 |
| EXECUTION_UNREALISTIC | 成交时点或可成交性不现实 | 使用事件引擎重写 |
| OVERFIT_RISK | 参数/试验选择风险 | 记录预算、PBO/DSR 和负结果 |
| TAIL_RISK_HIDDEN | 马丁格尔、无限补仓或风险控制缺失 | 拒绝/强制上限 |
| LICENSE_RESTRICTED | 权利不允许公开或复用 | 只保留允许的内部元数据 |
| DUPLICATE | 多名称共享同一经济语义 | 合并谱系，只计一个 Alpha |
| REJECTED | 关键门禁失败 | 不执行、不发布 |
