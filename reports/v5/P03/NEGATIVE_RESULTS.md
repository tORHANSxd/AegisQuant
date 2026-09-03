# V5-P03 负结果与禁止外推

- 验收使用确定性 DEVELOPMENT 数据，不是公开互联网搜索效果或事实核验准确率。
- 未测量 syndication/copy detection 的 precision、recall、误合并率或漏合并率。
- 未实现黑盒语义相似度、跨语言机器改写识别或 claim-span 级独立性拆分。
- 未验证搜索引擎覆盖率、来源许可变化、真实删除延迟或真实 first-seen 完整性。
- 未实现 Truth Council、Brier、ECE、calibration curve、retraction delay 或 source reliability。
- 未产生因果效应、forecast accuracy、净收益、回测或 forward trading evidence。
- 所有 P03 工件均不满足 Alpha Promotion；实盘、下单和真实账户连接继续关闭。
- 完整 CI 前三次运行分别暴露并修复了公开 SHA 被误报为 secret、候选 Python 状态先读后写、
  候选报告更新后 P00 哈希快照过期三类问题；只有修复因果顺序后的第四次完整运行 59/59
  通过被用于最终验收，失败结果未被掩盖或拼接成通过。

十个网页一起复读一条匿名传闻，不叫“十方会审”，叫复制粘贴办团建。P03 只负责别把这个
热闹误算成证据。
