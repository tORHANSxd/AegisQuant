# B6 ML 契约

入口 `python -m scripts.run_alpha_v5_walkforward --config configs/research/alpha_v5_ml_contract.yaml --preflight-dir <已核验目录>` 只生成一次独立封存的工程报告。真实研究的五项预算均为 0，未启用真实训练。旧 generation、失败日志和历史模型结果保留。

`SampleSpan` 的版本化扩展记录 `feature_dependency_start`、`label_available_time`、`episode_id`。严格分割以完整闭区间执行 purge，日历分区右端不含；跨资产同一时间组、同 episode 同步剔除，所有 train/val/calibration/test 交界及测试尾部均检查。固定 bar purge 只是额外缓冲，不能替代长 episode 的真实信息尾巴。未提供新策略时保留旧序列化和分割身份；严格结果有独立契约哈希。

episode ledger 从冻结的完整基础机会集生成，ID 缺失或只提供 ML 接受者报错。标签复用原生成器，记录实际可知退出原因、label 可用时间、成本、MAE/MFE 和资本秒数。输入冻结集 hash 仅证明所供记录内部一致，不证明外部机会完整；所有此路径收益是冻结基础策略的反事实，不冒充实际成交获利。

OOF 预测必须绑定 purged inner-train 样本及转换器拟合 ID、标签契约、模型/数据/split hash 和时钟。禁止同 episode、同时间、特征或标签依赖交叠；转换器也只能拟合该 fold 的训练样本。`fit_economic_filter` 的严格路径接收逐条 OOF、outer fit 与测试依赖元数据，并在实际拟合前核对训练内容及模型配置。旧单验证集调用保留为历史兼容。风险减仓独立于模型可用性。

三个 outer 块完整覆盖 `[2022-04-01,2025-10-01)`；inner 验证取每个 outer-train 最后九个月的三块三个月。没有真实样本时仅登记日期，purge 后实际行数、有效 episode 和独立时间块保持未知，不能用原 30 行校准门槛证明统计充分。未来 24 个基础模型 fit 加 120 个 outer 均值区块重拟合、6 个最终校准 fit 是拟议预算，当前不执行。outer 重拟合不能回填为包含其训练样本的 OOF；内层均值不确定性和额外校准没有授权预算。

新 DSR wrapper 要求完整候选史、逐期 Sharpe、raw kurtosis、样本依赖依据及保留全部候选的相关性口径；不足返回 null。新 PBO wrapper 接受每分段每候选的原始逐期收益，并使用与实际预登记选择一致的均值或 Sharpe；训练并列均匀加权、测试并列 mid-rank，无法辨识不制造排名。旧统计函数留给原报告复现。

合成验证不能证明真实 OOF 覆盖、经济增量或候选准入。conformal 只描述预测残差区间，不是均值置信区间，也不保证非平稳时序精确覆盖。真实 PIT、执行/组合、成熟 episode、独立块数量、全试验史和模型选择冻结仍是推进条件；最终 `NO_PROVEN_ALPHA / CASH`，四个开关关闭。
