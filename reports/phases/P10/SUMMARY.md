# P10 实施总结

P10 已完成全球多源事件智能、证据图、叙事状态、事件影响融合与时点回放的工程实现；正式验收按
项目业主决定延期。阶段保持 `in_progress`，不生成 `ACCEPTANCE.md`，不写入
`accepted_at_utc`，`LIVE_TRADING` 继续锁定。

## 已交付

- FRED/ALFRED vintage-aware、Coin Metrics Community、Dune、DeFiLlama、GDELT 原始来源追踪，
  以及官方交易所、项目方、监管机构、法院、央行和 ETF 发行人目录的只读契约。
- X、Telegram Bot API、Bluesky Jetstream v2、YouTube、GitHub 的许可、配额、游标、缺口、回填与
  安全降级模型；Reddit、Discord 和未知权利来源默认禁用。
- 原文、规范化、翻译审计、修订、删除 tombstone、互动快照、近重复、转发家族与跨平台实体链接；
  一百条同源转发只贡献一个独立证据家族。
- Claim 支持/反驳、EventCluster、NarrativeState、来源可信度与独立性评分，以及 Fast/Deep、
  Skeptic、冲突和结构化弃权的可审计委员会路径。
- BTC/ETH 多时域事件影响 Proposal，与价格、订单簿、OI、资金费率、基差和链上六类 PIT 特征融合；
  Market-only、Event-only、Fused、Risk-only 使用相同样本和预算并保留正负结果。
- 修订与互动 as-of 回放、5/30/120/600 秒延迟压力、未来互动泄露、趋势前置和安慰剂检查，以及
  Event Radar、Evidence Graph、Narrative Monitor、Source Monitor、Event Replay 五个只读模型。

## 生产状态与边界

P10 的机器证据由项目自有确定性夹具生成，验证的是接口、时点、权利和安全契约，不冒充生产源已
上线，也不构成 Alpha 或盈利声明。需要凭据的来源保持 `AWAITING_CREDENTIALS`；没有连接真实交易
账户，没有访问秘密存储，没有请求或写入密码、Cookie、验证码、API Secret 或 Telegram 用户会话。
Dune 仅登记只读 SQL 版本与结果清单，不执行写 SQL；GDELT 仅作为发现层。

## 验证状态

完整 CI 33/33 阶段通过；Python 3.13 全量测试 441/441、Python 3.14.7 隔离候选契约 404/404
通过，严格 Pyright 与 Ruff 均为 0 问题。确定性证据重放和 10/10 关键变异通过。Secret 命中 0，
Python/JavaScript 依赖审计、Bandit、SBOM 与许可证清单通过，Python 未知许可证计数为 0；前端
lint、类型检查、单测、生产构建与 Playwright E2E 全部通过。

首次候选预跑因最终报告尚未生成而出现 1 个顺序性失败；第一遍 CI 还发现 P04 的 Bluesky v1
证据未随 P10 v2 主契约更新。P04 现明确记录为 legacy v1 回退，补齐真实报告后完整重跑全绿；
两次预跑失败均保留在 `TEST_RESULTS.json`，没有拿局部通过冒充最终成功。

实现提交为 `1ee49a5a8a460b6152b86393d6284c3fea82010d`。最终流水线结果与工件哈希分别见
`CI_RESULTS.json`、`TEST_RESULTS.json` 和 `ARTIFACT_MANIFEST.json`。
