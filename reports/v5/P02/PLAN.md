# V5-P02 — Source Registry + Identity + C2PA

- Evidence Tier: `DEVELOPMENT`
- Alpha Promotion Eligible: `false`
- Live Trading Locked: `true`

## 规格边界

本阶段严格对应 v5 SSOT 第 279–391 行及 V5-P02 第 2058–2074 行，只实现来源注册、
官方身份规则、detached signature、C2PA provenance、内容完整性和来源攻陷状态。P03
检索与独立性图、P04 Truth Council/校准以及后续预测和交易能力均不提前冒领。

## 实施顺序

1. 建立版本化 `SourceRegistry`，覆盖来源身份、域名、账号、公钥、endpoint、许可、历史
   指标、攻陷事件引用及 `valid_from/valid_to/available_at`。
2. 建立多因素官方身份判定；域名字符串单独出现永远不足以认证。
3. 建立 PIT 公钥解析、fingerprint 校验及 detached signature 正负验证。
4. 接入官方 C2PA Python SDK，解析 2.x/2.3 元数据、信任、签名、时间戳、ingredient、
   content binding、generator、AI assertion、证书和篡改信号。
5. 将官方身份、内容完整性、来源攻陷和声明真值保持为独立契约并绑定到原始内容 hash。
6. 生成 schema、确定性开发证据、负向测试、完整 CI 和内容寻址工件清单。

## Acceptance

- spoof domain、Unicode homograph 和未知 endpoint 全部 fail closed。
- 有效 detached signature 可认证，payload 篡改必须无效。
- 有效 C2PA 通过签名、测试 trust chain 和 content binding；字节篡改必须无效。
- 无 C2PA 输出未知/无凭证，不得自动判假。
- C2PA 有效不得推导 claim true。
- 官方身份可与 `COMPROMISED` 同时成立，且不得被改写成 spoof。
- 完整 V5-P02 CI、最终工件清单和清单自检全部通过。
