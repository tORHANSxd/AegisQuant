# Crypto Translation Queue

| Target | Source concept | State | Required rechecks |
|---|---|---|---|
| `crypto_trend_breakout` | 股票或期货趋势突破 | implemented_synthetic_validation | 上下币幸存者偏差, 跨所流动性, 资金费率, 拥挤反转 |
| `utc_session_reversal` | 传统市场开盘/收盘反转 | implemented_synthetic_validation | 时区稳健性, 周末状态, 延迟, 流动性分层 |
| `funding_basis_carry` | 商品期货期限结构与展期收益 | implemented_synthetic_validation | 资金费率修订, 借贷成本, 保证金, 多腿裸露, 交易所风险 |

真实来源导出到达后必须重新建立证据、审计和经济语义；当前三项不是来源策略复现。
