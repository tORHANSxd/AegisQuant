# AegisQuant R4 配套包

先阅读 `AegisQuant_R4_低换手与连续持仓优化任务书_20260908.md`。

本包基于本轮用户粘贴的新 A1/A3/A7 报告，而不是以前的 B3/B5/B7 附件。`snapshot.json` 是手工摘录；本包没有用户原始 results.json、最新本地源码或逐笔 Parquet。

## 已执行

- 对最新报告中的汇总数值做 Decimal 算术，输出 `derived_metrics.json`。
- 运行缓冲目标参考组件的 40 项独立单元测试；真实输出见 `test_results.txt`。
- 查询公开 GitHub 最新提交；新本地运行目录在所读提交不可用。

## 未执行

没有将参考代码接入用户原事件引擎，没有执行新的市场回测或全仓测试，没有修改本地或远程仓库，没有启动账户、纸面交易或实盘。40 个测试通过不代表策略盈利。

## 独立运行

在本目录使用 Python 3.10 或以上版本：

```text
python summarize_report.py
python -m unittest discover -s tests -v
```

代码只使用 Python 标准库。本地集成应使用项目自身锁定的环境。

## 迁入边界

`buffered_target.py` 只提出数量目标，不发单、不给盘口作假、不记账。集成必须保留原账户余额、订单管理、数量精度、最低金额、手续费、风险联动与真实成交更新。

传入 `regular_review_due_override` 保持 A1 原调仓日历。RECONCILE_PENDING 要由已有执行器决定复用、等待还是撤单，不能当作无条件撤销所有挂单。

生产仍保持 CASH 和所有订单提交关闭。只把这一包作为本地 Codex 的有限研发任务，不将默认参数当作已验证实盘配置。
