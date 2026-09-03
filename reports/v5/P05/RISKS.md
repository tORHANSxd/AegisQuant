# V5-P05 风险

1. **MarketReflectionScore 不是概率。** 十维加权和与 `0.80` 阈值是版本化开发政策，没有真实
   标签校准；UI、报告和后续模型不得把它显示成统计意义上的 probability。
2. **缺失数据不能等于市场没反应。** 任何必需指标缺失或过期都返回 `null + DEGRADED` 并阻断
   方向候选，避免“没数据=没定价”的经典送命逻辑。
3. **verified source 不等于 confirmed fact。** 已验证账号发布 rumor 仍是 rumor；只有可见的官方
   `FACT + AFFIRM` 和 Truth state 才能确认，官方否认走 denied。
4. **响应时间可能受采样频率影响。** price/volume response lag 只记录输入快照可证明的时间，
   不把采样点当作事件真正影响市场的精确瞬间。
5. **同源转发会夸大扩散。** 当前 snapshot 明确保留 independence group，但真实数据仍需 P03
   provenance graph 和后续标注验证，不能单靠文章数量判断扩散强度。
6. **数值 Surprise 的符号依赖经济语义。** `actual-consensus` 是原始 surprise，某指标“更高”对
   资产是利多还是利空必须由后续事件类型/因果模型学习，P05 不硬编码方向。
7. **兼容入口仍存在。** 为避免一次性破坏旧调用，旧参数签名暂留；但输出已 fail closed。后续
   迁移完成后应删除废弃入口，避免调用方误以为它仍有方向能力。
8. **工作树 Manifest 不是外部不可篡改锚。** 历史 SHA 自洽能发现普通漂移，不能替代受保护远端、
   签名或透明日志。
9. **没有因果或交易证据。** P05 不证明事件造成了价格变化，也没有真实净成本回测；任何 Alpha
   或 Promotion 表述都应视为越权。
