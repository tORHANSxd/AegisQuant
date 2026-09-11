# B2：PIT 数据契约与合成验证

本批在已有 main 上实现 B2，沿用 B0/B1 的零历史回放、零真实拟合、零最终留出访问和零订单约束。
原 R5 v3、R4、B0/B1 v1/v2 的证据和失败记录不覆盖，G1 参数、交易逻辑、费用及安全开关不改。
新 generation 为 `alpha-r5-pit-contract-20260910-v1`；配置为
`configs/research/alpha_v5_pit_contract.yaml`，输出到独占目录
`artifacts/alpha_v5/20260910_pit_contract_v1/`。不自动提交、归档、推送或进入下一批。

## 兼容与新语义

`UniverseMembership.evidence` 是可选证据包装。不提供时，旧 `membership_id` 的 canonical payload
完全不变，旧调用无需补虚构字段。新证据明确业务事件 ID、不可复用的 instrument UID、展示符号、
交易所、事件种类、发布时间、首次接收时间、修订和 source hash。事件修订先按当时可知信息选择，
再应用生效时间。同事件同 revision 冲突失败；同一时刻不推断相互冲突事件的隐含优先级。

已公告但未生效的事件保留为已知前缀；晚到的历史修订不能回写过去。
有归档发布时间证据时，今天下载不自动抹掉历史可知性；只有接收证据时，不能把可知时间倒填到公告前。
同名重上市必须使用新 UID；同 venue/symbol 同时对应两个可交易 UID 时失败。

`eligible_universe_at` 默认保留 legacy count-only 路径。`strict_evidence=True` 或
`audit_universe_at` 使用 B2 严格契约：全部入选、排除及未知结果有原因和内容哈希；只决定新开风险，
不改变已有持仓，不免费退出或伪造退市回收价。真实严格路径不接受合成证据。

## 连续历史、流动性与规则

流动性窗口为 `(window_start, window_end]` 的闭合四小时事件，跨度恰好 30 日、180 个 UTC 网格点。
明细逐行有 close/available time、真实 quote turnover 或逐笔 quote 求和的方法身份及 source hash。
字符串金额通过 Decimal 处理并与明细精确求和对齐；`base_volume * close` 明确是 proxy。
明细重复、哈希错误、提前可知、汇总不等或虚报连续根数失败；缺口和缺件不能填零后升级为完整证据。

按当前 `build_trend_features` 的索引与收益依赖，40/80/160 日趋势分别至少需要 241/481/961 根，
42 个收益的波动计算至少需要 43 根；新严格契约取所有登记依赖的最大值。
240 根只表达 legacy 最小历史，不覆盖最长依赖。交易暂停恢复或新生命周期后保守地重新证明连续历史；
这不修改冻结策略的 warm-up 实现。未来若接入 covariance，须另行登记其窗口，不能从当前参数猜测。

`RuleProvenance` 包装现有 `HistoricalInstrumentRule`，复用 `HistoricalRuleBook` 的有效时间选择。
增加当时可知时间、修订、公共现货规则 scope、源和 payload hash，以及价格/普通与市场数量规则、
notional 与订单权限的原始过滤器引用。未知、proxy、过期或停用规则不能开新风险。
本批只校验来源和资格契约，不替换执行模型，也不把这些字段称为已实证费用或完整成交验真。

## 入口和证据不足

```powershell
.\.venv\Scripts\python.exe -m scripts.run_alpha_v5_research pit-audit --config configs/research/alpha_v5_pit_contract.yaml --preflight-dir <本批前置保全及测试记录目录>
```

新命令不进入 legacy `register/run/report` 分支。输出目录和任务 claim 独占创建；失败也消费唯一数据质量槽，
保留 ERROR 日志及 manifest，不能删目录重跑。原 legacy 研究函数体保持不变，未执行它们的回放测试。

默认没有真实 `universe_events`、`liquidity_windows`、`rules_provenance` 或全市场 coverage manifest；
流动性阈值也未另行登记。因此数据质量作业应以 exit 2 和 `FAILED_CLOSED_INSUFFICIENT_PIT_EVIDENCE`
停止，工程测试可完成。未知数据用 `records=null` 加状态表达，绝不把缺件当空 universe 或 0 收益。
合成示例阈值只用于测试，不回填为历史研究参数。实际文件只能来自明确登记的
`data/research/pit` 路径及 hash；保护 holdout、symlink/junction 与凭据路径在打开前拒绝。

当真实文件另行登记时，coverage manifest 必须绑定候选 UID（含退市资产）、开发期及每个归档源 hash。
删除今日已退出资产、改源表或来源哈希错配会失败；未来新增不可知数据只影响新的来源文件身份，
不改变旧时点的可知资格快照。源方全市场覆盖声明与独立市场普查仍分开，不因一个布尔字段自动取得晋级。

产物包括四类 schema/来源表、`asof_snapshot_manifest.json`、`future_mutation_report.json`、缺口表、
预算/安全检查、原文件备份、本批 implementation、差异补丁、实际测试记录与 `OUTPUT_MANIFEST.json`。
future-mutation 仅验证 PIT 事件、流动性、规则和跨币资格快照；未重新验证价格特征、组合风险或订单/成交前缀。
仅运行指定 B2 纯测试及既有纯 PIT 测试，不运行全仓 pytest，不把旧回放日志当本批通过。

最终仍为 **NO_PROVEN_ALPHA / CASH**，ML、纸面准入、实盘及订单提交全部关闭。
