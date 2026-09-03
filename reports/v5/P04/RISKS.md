# V5-P04 风险

1. **小型合成 fixture 容易显得过分漂亮。** 58 个确定性样本只用于执行契约；任何 Brier、
   PR-AUC 或 high-confidence accuracy 都不得外推到真实新闻。
2. **校准方法比较不等于用 test 选最好看的数。** P04 预先固定 Platt 为选定方法，其余三种
   仅作为 shadow comparison；否则会把 test 变成另一个 validation。
3. **切片样本不足。** 四个 source/event/language/claim 组合在 test 中各只有 3 条，部分切片
   缺少类别变化，明确标记 `INSUFFICIENT_CLASS_VARIATION`。
4. **经验层级 Bayesian 是透明候选，不是万能真相机。** 它按校准 key 向全局 Beta prior
   收缩，真实层级结构、交互和漂移仍需真实 PIT 标签检验。
5. **来源可靠度只降不自动升。** 这是 fail-closed 策略，能防止短期好转洗白历史；恢复必须
   经过独立治理和新版本策略，不能靠一次观察自动翻篇。
6. **模型 lifecycle 不自动恢复。** `RETIRED` 等状态需要人工治理的新版本替代；否则同一模型
   可能借较短的好窗口重新进入生产。
7. **标签 availability 是关键上游事实。** 真实数据若只有最终真值、没有首次可知时间，依然
   不能用于 PIT 校准或回测。
8. **Conformal 点概率误用风险。** P04 不把需要时间序列覆盖诊断的 interval conformal 硬塞
   进二元 Truth probability；adaptive/distribution-aware conformal 留到 V5-P09。
9. **工作树内 manifest 不是外部不可篡改锚。** 固定 SHA 与 artifact-set 校验能发现非协同误改，
   但有权同时修改 state、测试和 manifest 的主体仍可整体重写；生产治理需受保护远端、签名或
   透明日志。
10. **CI 包含 build 步骤。** legacy compliance、compatibility 和 P00 reset 会生成带时间戳或
    派生证据；它们是完整兼容性 gate 的一部分，不是 V5 阶段越权。最终 snapshot 必须在 CI
    之后生成并再次校验，不能拿 CI 开始前的 manifest 冒充最终工件。
11. **Lineage 内容地址仍需要外部信任根。** P04 会验证 claim/source/document/revision 绑定，
    并把 claim 与 evidence 的实际 content hash 对回输入快照；但其他派生 signal hash 是否已在
    受保护 registry 落盘，不可能由纯数据模型自证，生产前必须接入不可追加篡改的 artifact store。
