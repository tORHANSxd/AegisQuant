# V5-P03 风险

1. **确定性信号不是语义真相。** 相同 hash、origin、owner 或显式 lineage 可高精度合并，
   但会漏掉没有这些元数据的隐蔽机器改写。缓解：P03 不虚构 NLP 召回率，后续必须用真实
   标注集校准相似度候选。
2. **共享来源不等于共享结论。** 两篇报道引用同一匿名人士时，其核心事实证据仍只有一份；
   但记者的独立核验部分可能不同。缓解：分量可审计，未来按 claim span 细化，不在 P03
   拍脑袋拆分。
3. **错误 provenance 会污染独立数。** 上游 origin 或 ownership 标错会误合并/漏合并。
   缓解：保留具体 component member、graph hash 与 source lineage，不只输出一个分数。
4. **Rights UNKNOWN fail closed。** P03 的证据选择同时排除 `UNKNOWN` 与 `PROHIBITED`；
   `LIMITED` 是否可用仍须满足既有 source policy，不能借本阶段绕过 policy gate。
5. **PIT 依赖真实 first-seen。** fixture 中的时间语义正确不代表历史第三方文章有可靠
   first-seen。无可靠时间的回测仍不可作为 Alpha 证据。
6. **高依赖只是不增信，不自动判假。** 十篇转载仍可能复述真实信息；本阶段只阻止伪多源
   加分，Truth probability 属于 P04。
7. **历史生成器不能用新语义回写旧证据。** P03 的图模型会改变 P01 generator 的实时输出。
   缓解：历史报告只按冻结 manifest SHA 验证；全仓 pytest 负责代码回归，当前阶段只重放
   当前证据生成器。
8. **Web E2E 清理阶段出现 Windows WebSocket reset 日志。** Playwright 三浏览器阶段退出码
   为 0，断言全部通过；日志来自客户端关闭连接后的 server transport 清理。若后续出现用例
   失败或资源泄漏，再单独修复 transport shutdown，不在 P03 把无失败日志包装成故障。
