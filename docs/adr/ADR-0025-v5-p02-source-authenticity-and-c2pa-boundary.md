# ADR-0025：V5-P02 来源真实性、C2PA 与声明真值边界

- 状态：Accepted for development
- 日期：2026-09-03
- 决策范围：V5-P02 Source Registry、官方身份、内容完整性与来源攻陷状态

## 背景

域名、账号、签名、C2PA 和事实真值不是同一个东西。域名可以被拼写仿冒，官方账号可以
被攻陷，签名只证明密钥控制，C2PA 只证明 provenance assertion 与资产的密码学绑定。
如果把这些信号揉成一个 `verified=true`，系统迟早会非常自信地把假话盖成真章。

## 决定

1. 建立版本化 `SourceRegistry`。域名、稳定账号 ID、公钥和 API endpoint 都必须来自
   decision time 可见的 registry 版本；来源级别只作为 prior，不作为 verdict。
2. 单独域名匹配只能得到 `INSUFFICIENT_EVIDENCE`。官方身份至少需要稳定账号 ID、有效
   detached signature，或域名与精确已登记 endpoint 的组合；任何不匹配均 fail closed。
3. detached signature 当前只接受 registry 明示的 `ED25519` 公钥，并校验公钥
   fingerprint、有效期、撤销时间、source identity 和 PIT 可用时间。
4. C2PA adapter 固定使用官方 `c2pa-python==0.37.8`，底层为 `c2pa-rs`。目标兼容
   C2PA 2.x、优先识别 2.3；返回 manifest、签名、trust、timestamp、ingredient、content
   binding、generator、AI assertion、certificate 和 tamper 的独立状态。
5. 默认关闭 remote manifest 与 OCSP 网络获取，避免验证阶段发生隐式外连、SSRF 或不可
   重放依赖；生产 trust-list 更新与吊销策略必须由后续受控流程另行决定。
6. `ContentIntegrityAssessment`、`OfficialIdentityAssessment`、`SourceCompromiseEvent` 与
   `ContentAuthenticityBinding` 保持独立。`C2PA_VALID` 和 `AUTHENTIC` 都不得推导
   `claim_truth_probability`；无 C2PA 记为 `NO_CREDENTIALS`，不得判假。
7. 测试签名私钥和 C2PA 证书只在临时目录内确定性生成，不提交任何私钥。自建 root 只用于
   DEVELOPMENT 负控，不具备 C2PA conformance、公共 trust-list 或生产信任含义。

## 证据

- `data/catalogs/v5_source_registry.yaml`
- `reports/v5/P02/SOURCE_PROVENANCE_EVIDENCE.json`
- `schemas/events/c2pa-verification-v1.json`
- `schemas/events/content-authenticity-binding-v1.json`
- `tests/v5_p02/`

## 后果与回退

- 好处：来源、内容和事实三层信号不会互相冒名顶替，历史决策可按 PIT 重放。
- 代价：默认不联网会留下 timestamp/revocation 的未知状态；真正生产部署需要受控 trust
  运营，而不是往配置里塞个 URL 就假装安全。
- 回退条件：若 SDK 版本或 trust 模型变化，新增 superseding ADR 和兼容测试；不得原地
  删除“C2PA 不等于事实真值”这一边界。
