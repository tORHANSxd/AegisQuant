# Reproduction Scoreboard

三项均为 AegisQuant 从零重写并使用同一 P06 事件引擎、规则和成本政策运行的合成验证。
结果只证明订单→成交→账本→指标可复现，不证明 Alpha 或未来盈利。

| Candidate | Engine | Orders/Fills | Net PnL | Total return | Economic hash |
|---|---|---:|---:|---:|---|
| `crypto_trend_breakout` | EVENT | 2/2 | 1.8941601216 | 0.00018941601216 | `1ebe60b4bc86a393c2987d6baad01b43b8a02d6a2a20e9bb7a90ea833f093611` |
| `utc_session_reversal` | EVENT | 2/2 | 7.8981924864 | 0.00078981924864 | `3816e4ecfc65732323b72898435477ecbf64a362f0e8103101e47e979c8ce2bd` |
| `funding_basis_carry` | EVENT | 2/2 | -2.0563321216 | -0.00020563321216 | `8730b28b4af850e90c8036bfc2796aa36561a5c1d814de8b7a410a71c397dcd2` |

真实聚宽来源复现：`NOT_RUN_STATIC_ONLY / awaiting_user_export`。
外部来源收益采用：`false`；来源代码执行：`false`；Live trading：`locked`。
