# ADR-0012：P07 特征、验证、基线与最终 Holdout 政策

- 状态：Accepted by project owner through approved P07 plan
- 日期：2026-09-01

## 背景

P07 必须建立朴素但可信的研究基准。主要风险不是模型能力不足，而是未来数据泄漏、随机时间
切分、修订和互动回填、成本口径不一致、只保留最佳试验、反复窥视最终 holdout，以及用复杂度
掩盖没有净经济增量的结果。

项目当前已有 P02 point-in-time join、P04 事件 revision/互动快照、P05 权威账本和 P06 历史
成本与回测引擎。P07 必须复用这些契约，不得建立平行事实或收益口径。

## 决定

1. 每个特征使用版本化 `FeatureDefinition` 登记；决策只读取不可变 `FeatureSnapshot`。未登记、
   可用时间晚于决策时间、未经许可或来源清单不完整的特征失败关闭。
2. 在线兼容特征必须有同一公式的批处理和增量实现，并通过确定性 parity；仅离线特征必须显式
   标记，禁止悄悄降级。
3. 标签窗口、特征窗口和切分窗口分离；purge 至少覆盖最大标签跨度，embargo 覆盖邻近泄漏。
   所有横截面样本按时间组处理，API 不提供随机 shuffle 时间切分。
4. 最终 holdout 通过状态机保护：只有数据、特征、标签、模型、参数、成本、split 与代码哈希
   全部冻结后才允许一次性开启；每次拒绝和开启都进入追加式审计链。
5. PBO 使用 CSCV 的样本外相对排名 logit；PSR/DSR 使用样本长度、偏度、峰度和总试验数修正。
   退化输入、样本不足、零方差或非有限值一律拒绝，不返回貌似精确的数字。
6. 多重试验至少报告 Benjamini-Hochberg FDR，并始终记录总试验数、失败与异常；阶段内使用
   追加式本地 Experiment Ledger，P08 可在不改变语义的前提下接入 MLflow。
7. 简单策略的成交与成本交给 P06，最终模拟现金流交给 P05；报告必须分列 gross、fee、spread、
   slippage、impact、funding、borrow 和 net，不能只按 Sharpe 排名。
8. Market-only、Event-only、Fused 使用完全相同的样本、切分、训练预算、随机种子、成本和指标。
   单一社交帖子只能是 `MONITOR` 或极低风险研究候选，不能创建订单。
9. 2026-09-01 以官方发布记录和实际解析为准，锁定 `scikit-learn 1.9.0`、`NumPy 2.5.2`。
   scikit-learn 1.9.0 官方记录发布日期为 2026-06，NumPy 2.5.2 官方记录支持 Python
   3.12—3.15；本机解析结果的包元数据也声明 Python 3.14，并已实际完成 Windows 3.13 契约。
   最终 3.14 契约由隔离运行验证；若解析或行为不符，更新本 ADR，不凭文档猜测。
10. 2026-09-01 检查 HKUDS/AI-Trader `main`：根目录未展示许可证文件；其 `research/`
    公开描述了可复现 paper dataset、统计表、bootstrap CI 与 FDR。P07 仅借鉴“可复现导出、
    保留实验过程、报告多重检验”的设计原则，不复制、执行、安装或派生其代码，也不调用其
    注册、copy trading、broker sync 或 live trading 能力。旧 R331 未由用户提供时不生成伪基准。

## 后果

- 研究路径更啰嗦，但任何模型结果都能追到可用时间、数据与代码哈希、切分、成本和全部试验。
- 最终 holdout 不是普通测试折，冻结前无法通过正常 API 读取；一次性开启后不能回到调参状态。
- P07 只交付经典基线和公平消融；MLflow、Optuna、树/深度模型、Model Council 与 AI 代理属于
  P08，不能偷跑。
- 新增依赖必须进入锁文件、SBOM、许可证和漏洞扫描；`LIVE_TRADING` 继续锁定。

## 外部契约依据

- scikit-learn 1.9.0 release notes：<https://scikit-learn.org/stable/whats_new/v1.9.html>
- NumPy 2.5.2 release notes：<https://numpy.org/devdocs/release/2.5.2-notes.html>
- HKUDS/AI-Trader：<https://github.com/HKUDS/AI-Trader>
- HKUDS/AI-Trader research pipeline：<https://github.com/HKUDS/AI-Trader/tree/main/research>
