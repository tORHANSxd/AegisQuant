# V5-P02 风险

1. **Provenance 不等于事实。** C2PA 或 detached signature 有效只证明声明与资产/密钥的
   绑定。缓解：契约固定 `claim_truth_implied=false`，Truth 仍由后续证据裁决。
2. **Trust 运营尚未实现。** 当前验收使用临时自建根证书；没有生产 trust-list 刷新、OCSP
   或撤销缓存。缓解：只标 `DEVELOPMENT`，默认关闭外连并保留未知状态。
3. **来源历史指标没有数据。** Registry 的准确率、纠错率、撤稿率和首报延迟均保持
   `null`，没有拿脑袋拍个 0.99。动态可靠度属于 P04 校准范围。
4. **官方账号也会被攻陷。** authentic identity 不能抵消 compromise。缓解：两个状态独立
   存储，并由绑定对象同时携带。
5. **C2PA 版本可见性不完整。** SDK 常规 reader JSON 未必暴露 manifest spec version；未知
   时输出 `UNKNOWN`，不根据 SDK 版本猜测 C2PA 2.3。
6. **默认无网络验证是安全与完整性的取舍。** 它避免不可重放外连和 SSRF，但在线吊销与
   remote manifest 只能留给受控后续流程。
7. **完整 CI 复跑历史 P03–P18，不代表未来 V5 阶段已完成。** `scripts/ci.py` 对 V5 阶段
   使用 legacy P18 作为全仓回归范围；V5 进度只由 `state/V5_PROJECT_STATE.yaml` 和当前
   `reports/v5/Pxx/` 验收决定，P03 未经 P02 封口不得授权。
