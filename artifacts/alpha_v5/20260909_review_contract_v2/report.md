# R5 B0 与 B1 只读／合成证据契约审计

**NO_PROVEN_ALPHA / CASH。ML、纸面准入、实盘及订单提交全部关闭。**

本批 generation：`alpha-r5-review-contract-20260909-v2`。实际读取已提交基线 `d8c6d4013097f6323ab8b7a424c860ba0ccbd62b` ＋本地冻结 R5 v3 源码与保存表；近期证据始终是 R4 F3。
历史策略回放 0、真实模型拟合 0、真实校准拟合 0、最终留出访问 0、真实订单 0；没有重算显著性。
报告累计尝试 2 次，每个独占 generation 使用 1 个报告槽；此前失败均保留并纳入 failure_history_index.json。
原始市场逐行审计、逐单资金账本重建和完整 trace→order→fill 联结未完成（NOT_VERIFIED）。

## 实际证据范围

20260909 精简包、版本图、包补丁、MANIFEST、原 readable CSV 及完整 ZIP 未收到（NOT_RECEIVED）。随附算术审计 JSON 是历史审阅记录，本批未冒称完成其中的 2,465 文件包验证。
使用本地冻结 Parquet 和 JSON 完成 Decimal 算术核对；新 readable CSV 仅是本批派生导出。原 result.json.gz 与 trace 文件存在，已核对哈希／schema，但未解压重建原始逐单凭证。完整新 trace 字段也未保存。
G1 近期试验没有执行，状态为 NOT_COLLECTED；近期 F3 没有改名、拼接或变为 G1 样本外。

## 算术、成本与统计

- 17 个 arm/cost 组合共同 UTC 日历与四小时日历、50,000 USDT 初始资金、cash + inventory = equity、终值和 14 季度复合核对通过；空仓日及付费终止边界保留。
- R5 派生成交 3181 行，R4 13504 行；所有组合的成交数、普通调仓理由数、名义金额及成本对齐保存汇总。G1 为 176 fills、12 次普通 resize，restore=0；F0 为 1814/2022。
- G1−F0 终值差 `16060.45311570832` USDT；账面成本节省 `1693.0537393882996`；各自路径终值加回成本之差 `14367.3993763200204`。最后一项不是零成本资金回放或 alpha。
- 三种成本模式分别命名；funded 模式不要求费用越高终值越低。35 个 same-fill 影子分组的嵌套成本和净值恒等式通过，实际 fill-path 身份及资金可实现性仍未验证。
- 原 9 个比较及其 raw/adjusted p、CI、bootstrap 元数据完整保留。p 值对应日均收益差；CI 对应未作多重校正的复合收益差。未重采样；DSR/PBO 与独立 trial 数均为 null。
- G1 原五项 churn 门槛通过与 NO_PROVEN_ALPHA 同时保留；盈利季度 6/14、Holm 未通过仍是旧研究结论。
- 容差提前固定：保存 Float64 表的资金 1e-8 USDT、收益 1e-10；原字符串成本分项 1e-18 USDT。残差逐组输出，无静默取整。无原始现金流账本不能凭余额恒等式排除历史额外入金。

## G1 合成机制

方差效用 `0.000008969199178644763860369609855` NAV；合成 16bps 的单腿成本 `.000112` NAV，成本／效用 `12.48717948717948717948717949`。增大乘在收益侧的 lambda 放宽门槛；移动远离 raw 的效用截为 0。16bps 没有被标作历史实测费用。
时钟表遵循冻结语义：到期且具备持仓／行情／趋势、无 pending 的复核先更新 review；成本否决也消耗该次复核。SUBMIT 更新 review，REJECT／FILL／CANCEL 本身不更新。pending 不凭空删除，硬退出仍受订单协调与真实可成交条件约束。
raw/smoothed/proposed 冲突、全部门槛漏斗、二次取整、gap 后所有指标 warmup、硬退出与尾部共同冲击列为待验证；不补造拒绝数或最差事件日期。

## 验证与保全

本批实际命令及全部结果见 `validation/test_commands_and_results.txt`，共记录 26 次检查调用；不是旧 1,188 项日志。仅执行新增纯测试及针对新文件的静态检查，未运行全仓 pytest。
实施前后 10478 个已有文件 SHA256 保持不变。用户 tracked/untracked 改动保留；没有 reset、clean、分支创建、提交或推送。新增文件与 diff 见 `changed_files.json` / `changes_this_batch.patch`。
现有失败代次、失败配置及 H3/H10/R24/R72 全部保留。错误会消费独占 generation 并保存日志；输出 manifest 以 exclusive create 封存，重用目录被拒绝。
本批 v1 因新审计器把派生 filled_qty 误当非负量而失败。冻结源码约定 BUY 为正、SELL 为负，名义额为正；v2 只修审计契约并增加买卖方向／零量反例，历史策略及源表不变。v1 是审计工程失败，不是新的 alpha 试验。

## 缺口与停止

包级版本／manifest 缺件见 evidence_gaps；现有原始文件只做 hash/schema 核对，完整原始账本联结和新字段仍未验证。真实历史费用、规则、盘口、延迟、PIT、全量独立试验史和未使用留出仍缺证据。
最小后续是另批提供精简包／完整包，核对包身份后只读联结现有原始凭证；若需要产生新的 trace 字段或历史机制消融，必须另获授权并使用新 generation。本批不进入该工作。
**本批完成即停止。最终仍为 NO_PROVEN_ALPHA / CASH，所有准入与订单开关关闭。**
