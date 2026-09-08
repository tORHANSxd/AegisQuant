# v4 指标契约

`direction_accuracy` 仅为预测诊断。真实值与预测值按同一个事前固定的经济中性带映射为 SHORT / FLAT / LONG；FLAT 不算作正确的 SHORT。混淆矩阵按该顺序输出。balanced accuracy 对实际出现的类别平均召回率，macro F1 固定平均三类，未定义 F1 记零。常量序列的相关性和 MCC 记空值。

R²_OS = 1 − SSE_model / SSE_past_benchmark。未提供事前历史均值预测时记空值，禁止用当前测试段均值充当可交易基准。[Federal Reserve 的样本外 R² 定义](https://www.federalreserve.gov/pubs/ifdp/2008/932/ifdp932.htm) 是该口径的参考。

三分类 Brier 为三个类别概率误差的平方和再对样本取均值。只有正类概率时，明确标记 LONG_VS_REST；ECE 使用事前固定的十个等宽概率桶。PT 符号检验排除真实或预测恰为零的样本，输出有效样本量；渐近独立假设只供诊断，不能替代分块 bootstrap。公式参照 [Pesaran–Timmermann (1992)](https://www.tandfonline.com/doi/abs/10.1080/07350015.1992.10509922)。

`evaluate_predictions` 未收到正值门槛、校准证据 SHA256 和早于评估起点的校准时间时，返回 NO_TRADE。归一化收益评估范围为 NORMALIZED_SIGNAL_SCREEN_NOT_EXECUTION_PROOF；原始资本 1 仅表示 NAV，不能替代交易所订单、流动性或保证金证据。破产路径拒绝继续筛选，必须转交有保证金约束的事件引擎。

归一化持仓按扣除交易成本后的权益确定：D = (wE − V) / (1 + w c sign(wE − V))。其中 c 是单边成本率，V 是交易前有符号敞口。每期收益作用于成交后的敞口；反转先平旧仓，再开新仓；最后一期完全退出并付费。gross_return 是相同权重的零成本复合收益；net_return 是扣费复合 NAV − 1；transaction_cost / cost_drag 是两条复合净值的差。实际扣款另列 cash_cost_paid，恒等式为 net_return = gross_pnl_on_net_capital − cash_cost_paid（Decimal 舍入残差单独报告）。成本/毛利润分母为完整交易中正毛 PnL 之和，不能用毛收益绝对值掩盖亏损。

交易统计按 flat-to-flat 完整往返聚合，同方向部分成交不会增加交易数；反转拆分两侧成本，资金费与借贷利息归属持有该资金流的交易。未平仓盈利不计入胜率。账户风险指标使用事前声明频率的 MTM 权益序列；Sharpe 年化因子来自时间频率，不能来自 fill 数量。回撤持续时间从最后峰值开始，未恢复的回撤累计至样本结束。终端 MTM 与扣除完整退出成本后的权益分别输出。

委员会只能选择净收益为正且统计、经济、压力和稳定性门槛全部通过并有证据哈希的候选。无合格候选时 selected_model_id 为空，禁止新开仓。预测损失改善本身不能证明经济增量。
