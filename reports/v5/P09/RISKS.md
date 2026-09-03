# V5-P09 风险

1. Meta-Reasoner 的自然语言解释容易被人误当成交易授权；契约虽无订单字段，界面与下游仍必须
   显示 `RESEARCH_RECOMMENDATION_ONLY`。
2. 上下文预提交且不同的 prompt/model hash 只能证明声明的路径与输出绑定不同，不能证明人员、训练
   语料或供应商层面的真实独立。
3. weight proposal、dataset、split 与预测的 SHA-256 仍依赖外部工件注册表，整体重算不能证明其来源真实。
4. 当前 distribution-aware conformal 使用预测区间 scale 归一化且按 cell 滚动，但有限样本 fixture
   不证明任意非平稳时间序列的真实覆盖保证。
5. OOD、数据质量与可靠度若由不可信调用方自报，仍可能被伪造；生产前必须由受控监控工件解析。
6. P09 Forecast governance 尚未成为 execution translator 的必选输入；P10 必须绑定 Forecast→Cost→
   Portfolio→Independent Risk，并禁止旁路。
7. 当前证据全是确定性 DEVELOPMENT fixture，不证明真实预测准确率、覆盖率或动态权重有效。
8. Final Holdout、Forward、Paper、Shadow、Testnet 和实盘均未开放。
