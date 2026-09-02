# P17 实施总结

P17 已完成付费 Provider Bake-off、受控试用、采购门禁和降级契约。候选目录覆盖 Tardis、Kaiko、
CoinGlass、CryptoQuant、Glassnode、条件式 Databento、个人级新闻三家、机构级新闻三家和 X API，
共 13 个候选、7 份最小试用协议。协议合计建议预算上限为 1080 美元，但用户批准预算为 0，激活试用
为 0，真实 Provider 网络请求、凭据请求、购买和真实试用均为 0。

当前采购结论为 `NO_PURCHASE`：12 个候选因缺少真实试用、OOS 消融、许可和运维证据而 `DEFER`；
Databento 因没有获批的跨资产或 CME 假设而 `NOT_APPLICABLE`。所有真实候选的数值评分均保持
`NOT_TESTED`/`null`，没有从营销材料编造质量或收益分数；运行时 Provider Registry 中付费候选批准数
和注册数均为 0。

评估内核已经固化相同研究预算、point-in-time OOS、官方交叉核验、完整成本扣除、多重比较校正、
负结果保留、许可、运行成本和停服降级门。确定性 fixture 只用于证明门禁本身能接受合格样本并拒绝
不合格样本，不代表任何商业 Provider 实测。新闻评估覆盖 recall、false alert、lead time、重复率和
风险覆盖；Provider 不可用或未批准时精确退回免费基线，任何第三方聚合均不能替代官方交易事实。

HKUDS/AI-Trader 仅用于思想级参考，没有执行脚本、加载远程 Skill、注册平台、复制代码或采用收益
声明。其 README 徽章声称 MIT，但复核时根目录 `LICENSE` 不可读取，因此许可证保持未核验，禁止
代码复用。

最终全链 CI 为 53/53 通过：Python 3.13.15 全仓 667 项通过，Python 3.14.7 隔离候选环境 628 项
通过，均有 11 条上游弃用告警；P17 定向测试 17 项通过，变异测试 6/6 全部击杀。Ruff、Pyright、
Bandit、Secret、Python/JavaScript 依赖、许可证、SBOM、容器/IaC、Web 构建与浏览器 E2E 均通过。
首次全链运行准确发现 P11 架构证据仍记录 59 个文件；P17 新增 4 个研究模块后重生成为 63，安全
结论未变，修复后的完整链通过。

按业主决定，本阶段不执行 12h/24h 墙钟验收，也不生成 `ACCEPTANCE.md`。以上只证明 P17 实现与
自动化门禁完成，不证明任何付费 Provider 具有真实增量，也不等于正式验收。没有连接真实账户、
没有索取或写入明文密码、Cookie、验证码或 API Secret，`LIVE_TRADING` 继续锁定。
