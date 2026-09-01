# P08 风险

## 已控制

- `P08-R01` 复杂模型因类别获得特权或使用不同口径：Council 强制相同 split、成本、预算、种子、
  目标与指标；复杂候选没有赢就被淘汰。
- `P08-R02` 失败试验、负结果或非最佳 trial 消失：追加式事件账本记录开始与全部终态，MLflow
  只是可重建投影，Optuna 成功、失败和剪枝 trial 全部保留。
- `P08-R03` 外部文本提示词注入或 AI 越权：Source Policy、Unicode/长度/秘密字段门禁和 Evidence
  ID 子集校验失败关闭；Provider 不提供工具、配置、秘密、账户或订单能力。
- `P08-R04` 基础模型权重与许可证不明：每个插件固定来源、revision、权重大小、许可证和
  SHA-256；Moirai 2、TimesFM 3 与未完成静态分析的 Kronos 不执行、不进入生产候选。
- `P08-R05` OOF 泄漏、状态追涨与不确定性被吞掉：OOF 折禁止训练/验证重叠，权重受限并平滑，
  conformal、校准、drift/OOD 和七类 abstain 具有确定性测试与变异门禁。
- `P08-R06` 完整 MLflow 与 `cryptography<50` 的漏洞/依赖冲突：按实际审计改用
  `mlflow-skinny 3.15.2` 与 `cryptography 50.0.1`，隔离契约覆盖 SQLite run、Registry version
  与 alias；完整 Server/Gateway 未安装也未启动，最终依赖审计通过。
- `P08-R07` Windows 原子目录发布偶发被短暂文件锁拒绝：保留原子 `os.replace`，仅对
  `PermissionError` 做 3 次、总计最多 60 ms 的有界重试，并覆盖模拟瞬时锁回归测试。

## 尚存且阻断对应正式验收项

- `P08-R08` 当前主机无 NVIDIA GPU，无法实测 4070 Ti 显存、训练时间和推断延迟上限；
  `P08-A07` 保持 `in_progress`，统一正式验收时必须在目标硬件重跑。
- `P08-R09` 历史事件回放只有公开发布时间和归档行情，没有真实采集系统的 first-seen 历史；
  结果只证明 point-in-time 流程，不证明因果或市场 Alpha。
- `P08-R10` Council 使用确定性开发契约夹具，胜出结果不能外推到真实资金、生产数据或实盘。
- `P08-R11` SQLite MLflow 与单机 Optuna JournalStorage 是个人研究基线，不具备多节点高可用语义。
- `P08-R12` 正式验收被项目业主统一后置。工程门禁可验证，但阶段仍是 `in_progress`，不得宣称
  已接受、可实盘或可解除 `LIVE_TRADING` 锁。
