# B0 与 B1 只读／合成证据契约

本批只新增证据契约、审计入口、任务配置和两个纯测试文件。审计身份是已提交
`d8c6d4013097f6323ab8b7a424c860ba0ccbd62b` 加本地冻结 R5 v3。
源码与配置、R4/R5 工件及失败记录保留原字节。没有自动提交、推送或分支操作。

运行入口：

```powershell
.\.venv\Scripts\python.exe -m scripts.audit_alpha_v5_evidence --preflight-dir <本批已记录的前置核验与测试目录>
```

配置为 `configs/research/alpha_v5_review_contract.yaml`。默认输出
`artifacts/alpha_v5/20260909_review_contract_v2/`；目录和报告 claim 独占创建。
复用现有 `registered_run` 和 `ExperimentEventJournal`，报告 kind 不计作 alpha trial。
成功、失败或已有空目录都不能被同 generation 重开。失败修复需另一个明确登记的 generation。

v1 的首次报告因新审计器错误要求 `filled_qty > 0` 而停止，失败目录已经封存。
冻结派生表约定 BUY 正量、SELL 负量，`filled_notional` 则是正名义额；v2 修正数量契约，
保留零量、负名义额、分项成本和普通 long-only resize 方向检查，并补充合成反例。
v2 按任务书 §3 创建新 generation，配置绑定 v1 manifest。每代报告槽为 1，累计报告尝试为 2
（一次审计工程失败、一次修复后报告）；五项禁止操作仍为 0，不计作两个 alpha trial。

前置目录含 `baseline_workspace.json`（实施前的分支、HEAD、全部本地改动路径及文件哈希）、
`workspace_before.patch`、`version_graph.txt`、`remote_main.txt`、
`test_commands_and_results.txt` 和 `validation_records.json`。它们在首次报告中按原字节保存。
最终新增文件 diff 和清单单独保存，不把用户原有未提交改动归为本批修改。

`evidence_contract.json` 列出实际读取文件、SHA256、字节数及用途。对保存 Parquet 的
Float64 列显式用 round-trip 文本转 Decimal；字符串成本保持原精度。资金容差为
1e-8 USDT、收益 1e-10、字符串成本分项 1e-18 USDT，来源是冻结表已经使用的浮点汇总
与字符串账务计算精度。没有通过静默取整消除残差。

所有 arm/cost 保留共同 UTC 日历和空仓日；季度按收益区间结束点减一微秒归属，包含已保存
付费终止边界。余额恒等式和终值核对不等于现金流或逐单账本重建。近期 F3 的最后半日
保留在完整资金报告，另示最后 UTC 日界及差额，不拼入 G1，也不标作未使用留出。

证据状态为 `VERIFIED / DERIVED_ONLY / HASH_ONLY / NOT_RECEIVED / NOT_COLLECTED /
NOT_VERIFIED / CONFLICT`。缺少精简包或完整包时允许受限报告，明确包级核验没有发生。
本地原始 result/trace 若存在，哈希／schema 检查与逐行联结分开；缺少完整字段时机制仍为
NOT_VERIFIED。没有执行过的近期 G1 列为 NOT_COLLECTED。历史算术审计附件和旧测试日志
只是保存证据，不计作本批运行。

成本模式：

| mode | 冻结对象 | 可作出的检查 |
|---|---|---|
| REDECIDE_FUNDED | 输入与策略规则 | 资金会影响决策和成交，终值无需随成本单调 |
| FROZEN_ORDERS_FUNDED | 订单意图 | 资金、拒单与部分成交仍可变；fixed orders 不是 fixed fills |
| SAME_FILL_SHADOW | 时间、数量、方向、参考价和库存路径 | 嵌套不利成本不得改善影子净损益，不保证可融资或可实现 |

已有影子汇总能核对算术，但缺原始 fill-path 联结时不能升级到完整路径验证。
G1−F0 的财富差、账面成本差、各自路径终值加回成本之差分别输出；后者不是零成本资金
回放或 alpha。原九比较原值保存：均值 p 与 compound CI 分别标 estimand；不重采样、
不换块长、不计算新的显著性。DSR、PBO 和独立 trial 数保持未知。

G1 方差案例直接调用哈希匹配的冻结纯函数，不执行历史 loader。时钟投影是合成事件表，
对应冻结 `cat_replay.py:502–513,837–847`：复核先更新、提交更新，拒绝／成交／撤单事件本身
不更新；pending 不凭空消失。新 trace schema 只定义未来所需字段，不回填历史数据。
raw/smoothed/proposed 冲突、全门槛漏斗、二次取整、gap 后全部 warmup、硬退出和尾部
共同冲击的完整历史证据不足时均明确列出，不补造次数或日期。

仅运行两个新增纯测试文件与相关静态检查。端到端 CLI 测试使用临时生成的合成保存表，
拦截策略／拟合／留出／订单入口及网络；真实报告运行也启用零预算调用及文件访问守卫。
保护数据目录和凭据内容不读取。所有原有文件的实施前后哈希、实际命令和结果进入报告。
`OUTPUT_MANIFEST.json` 哈希覆盖全部输出（自身除外）；它只能首次创建，修改可被校验发现。

结论始终为 **NO_PROVEN_ALPHA / CASH**；ML、纸面准入、实盘与订单提交全部关闭。
G1 原五项 churn 通过不构成统计支持或交易授权。本批完成即停止。
