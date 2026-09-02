# ADR-0022：P17 付费 Provider Bake-off 与零采购决策

- 状态：Accepted
- 日期：2026-09-02
- 决策范围：P17

## 背景

任务书要求只在免费基线可靠后评估付费数据，并以 OOS、成本、许可和运维证据作采购决策。当前没有
用户批准的预算、试用权限或本地秘密引用，也没有任何真实商业 Provider 样本。厂商文档可以证明接口
和计划“声称提供什么”，不能证明数据在 AegisQuant 假设中的净交易增量。

## 决策

1. P17 建立 Tardis/Kaiko、CoinGlass、CryptoQuant/Glassnode、条件式 Databento、个人级新闻、机构级
   新闻和 X API 共 13 个候选、7 份最小试用协议。所有协议的用户批准成本上限为 0，均未激活。
2. 没有真实试用时，许可、覆盖、延迟、修订/删除、缺口、语言、价格、运维和 OOS 净增量数值一律为
   `NOT_TESTED`/`null`；禁止从营销文案推导数值评分。
3. 采购门要求相同研究预算、point-in-time OOS、官方交叉核验、完整成本扣除、多重比较校正、负结果
   保留、许可通过和停服降级全部满足。同类首期最多批准一家；当前批准数量为 0，结论为
   `NO_PURCHASE`。
4. 13 个付费候选不写入运行时 Provider Registry 的 `approved`，也不成为依赖。Provider 停服或未批准
   时只返回现有免费基线。
5. 订单、成交、余额、仓位、保证金和交易规则始终以交易所官方接口及内部账本为权威；任何聚合源均
   不得替代官方交易事实。
6. 当前没有跨资产或 CME 批准假设，Databento 为 `NOT_APPLICABLE`，不使用其免费 credits，也不触发
   CME 许可或数据请求。
7. X API 当前采用按用量计费，限流与计费相互独立，精确价格只在 Developer Console 展示；未批准
   use case、预算、删除同步和 AI/ML 限制前不试用、不抓取、不用浏览器自动化绕过 API。
8. HKUDS/AI-Trader 只作思想级参考。复核时 README 徽章声称 MIT，但仓库根目录的 `LICENSE` raw URL
   返回 404，故许可证未核验；不复制代码、不读取其远程 Skill、不注册平台、不接入 copy trading 或
   Live。

## 官方依据（2026-09-02 复核）

- Tardis.dev：https://docs.tardis.dev/faq/billing-and-subscriptions
- Kaiko：https://docs.kaiko.com/explore-our-data/data-dictionary
- CoinGlass：https://www.coinglass.com/pricing
- CryptoQuant：https://cryptoquant.com/en/pricing
- Glassnode：https://docs.glassnode.com/basic-api/api
- Databento：https://databento.com/pricing
- Benzinga：https://docs.benzinga.com/introduction/introduction
- Event Registry：https://beta.eventregistry.org/plans
- CryptoPanic：https://cryptopanic.com/guides/how-to-integrate-the-cryptopanic-api
- RavenPack：https://www.ravenpack.com/products/edge
- Bigdata.com：https://docs.bigdata.com/
- LSEG MRN：https://www.lseg.com/en/data-analytics/financial-news-service/text-analytics
- X API：https://docs.x.com/x-api/fundamentals/post-cap
- HKUDS/AI-Trader：https://github.com/HKUDS/AI-Trader

## 后果

- 系统得到一套未来可以直接执行的有界试用和采购门，但当前不会产生费用、凭据请求或 Provider 网络
  依赖。
- 负结果、条件不满足和信息未知都有一等记录，不会因已有试用或沉没成本强行购买。
- P18 可以把“零付费 Provider、免费基线可降级”视为工程完成状态，但不能把未试用候选写成已验证
  增量；Live readiness 仍默认 `NO_GO`，`LIVE_TRADING` 继续锁定。
