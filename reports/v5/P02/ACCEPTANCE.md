# V5-P02 验收记录

- Evidence Tier: `DEVELOPMENT`
- Alpha Promotion Eligible: `false`
- Decision: `PASS_WITH_RECORDED_NEGATIVE_RESULTS`
- Live Trading Locked: `true`

| Gate | 当前结果 | 证据 |
|---|---|---|
| 版本化 Source Registry 与 PIT | PASS | registry hash、版本/前驱及 as-of 正负测试 |
| spoof / homograph / domain-only | PASS | 伪子域与 Unicode 同形域拒绝；单域名证据不足 |
| detached signature | PASS | ED25519 有效签名通过，payload 篡改、未知/过期/撤销/未来 key 拒绝 |
| 官方 C2PA SDK | PASS | `c2pa-python 0.37.8` / `c2pa-rs 0.90.15` 实际签验 |
| invalid C2PA | PASS | 签名媒体字节篡改被判 `INVALID`；异常类 fail closed |
| no-C2PA != false | PASS | `ABSENT` → `NO_CREDENTIALS`，tamper 保持 unknown |
| C2PA-valid != claim-true | PASS | provenance/integrity 契约固定不推导 truth |
| authentic + compromised | PASS | 同一绑定保留 `AUTHENTIC` 与 `COMPROMISED` 两状态 |
| 独立评审 | PASS | 三路只读审查；状态映射与负向测试缺口已修复 |
| 完整 CI | PASS | 60/60；pytest 727 passed；Python 3.14 为 653 passed；三浏览器 E2E 通过 |
| 最终工件清单 | PASS | 本文件完成后生成，逐路径/大小/hash 与 artifact-set 自检 |

记录的负结果包括自建 DEVELOPMENT trust root、无生产 trust-list/OCSP/remote manifest、
无来源可靠度校准和无真实世界 truth accuracy。因此本结论只授权进入 V5-P03，不授权
Promotion、实盘、下单或真实账户连接。
