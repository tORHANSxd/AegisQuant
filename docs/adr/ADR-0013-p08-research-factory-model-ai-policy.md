# ADR-0013：P08 研究工厂、模型许可、资源与安全 AI 政策

- 状态：Accepted by project owner through approved P08 plan
- 日期：2026-09-01

## 背景

P08 同时引入实验追踪、超参数搜索、编译型树模型、PyTorch、外部基础模型权重和 LLM 提案。
主要风险是失败试验丢失、搜索预算不可比、复杂模型获得类别特权、最终 holdout 被反复查看、
权重许可或供应链不明、外部文本提示词注入、AI 获得工具/秘密/交易能力，以及在没有 4070 Ti
的主机上伪造 GPU 验收。

当前主机为 Windows 11、16 GiB RAM，只发现 Intel 集显，`nvidia-smi` 不可用。项目已有 P07
最终 holdout 锁、P04 来源政策和事件证据契约，P08 必须复用并强化这些边界。

## 决定

1. 使用 MLflow 3 的数据库后端进行本地实验索引与 Model Registry；服务仅绑定 loopback，
   SQLite 保存元数据，工件进入本地内容寻址 Registry。P07 追加式 hash-chain ledger 是审计
   权威源，MLflow 是可查询投影；任一投影失败都必须在 ledger 留下 ERROR/未完成记录。
2. 不使用已弃用的 Model Stage。研究级 Champion/Challenger 使用 Model Registry alias 与
   validation tag；任何 alias 变化都要求显式非 AI 审批事件，自动训练不得自动发布。
3. Optuna 使用稳定版和单机 JournalStorage。每个 trial 在运行前登记预算与开始事件，在成功、
   失败、异常、剪枝或超时后写终态；禁止只记录最佳 trial。
4. 直接依赖必须精确锁定并通过 Python 3.13/3.14 Windows 契约。初始候选为 MLflow 3.15.2、
   Optuna 4.9.0、LightGBM 4.7.0、CatBoost 1.2.10、XGBoost 3.4.1、PyTorch 2.13.0；若实际
   lock、导入、训练、序列化、安全或许可证契约失败，停止并以新的 ADR 修订，不使用预发布版。
   初次 `uv lock` 证明完整 MLflow 3.15.2 要求 `cryptography>=43,<50`；随后实际安全扫描发现
   `cryptography` 49.0.0 的 `PYSEC-2026-3552` 仅在 50.0.0 起修复，同时完整 `mlflow` 分发包含
   无修复版本的 `CVE-2026-71211` Gateway SSRF 通告。因此最终改用官方 `mlflow-skinny`
   3.15.2，保留项目已有 SQLAlchemy/Alembic，并恢复 `cryptography` 50.0.1。隔离环境契约已
   验证 SQLite experiment/run、Model Registry version 和 alias；P08 不安装或启动完整 Server、
   AI Gateway 或远程代理。禁止绕过依赖解析或用漏洞 waiver 冒充通过。
5. 深度候选采用参数受限的 TCN 和 Patch Transformer。固定种子、线程和确定性算法；无法保证
   跨硬件位级一致时记录数值容差与后端，不能隐藏非确定性。
6. 四类基础模型均采用统一插件与显式 capability 状态。缺包、缺权重、硬件不足或许可受限时
   返回结构化不可用/abstain，禁止静默回退后仍冒用基础模型名称。
7. 有限 CPU 评测优先选择 Apache-2.0 的 `autogluon/chronos-2-small`，下载前固定 revision，
   下载后记录代码、配置、权重来源、许可证、大小和 SHA-256。权重保存在忽略的受控缓存，Git
   只保存元数据。Moirai 2 的 CC-BY-NC 权重和 TimesFM 3 的非商业/非生产权重默认只能作为
   许可研究条目，不能进入生产候选；Kronos 代码在 P09 静态分析前不执行外部仓库。
8. AI/LLM 只产生 `PROPOSAL`。输入经过 Source Policy、数据分类、Unicode 规范化、长度限制、
   注入检测和秘密/账户/订单字段拒绝；Provider 不暴露工具、文件、网络代理、配置或交易接口。
   输出必须通过 JSON Schema、Evidence ID 子集、冲突和置信度校验后才可进入人工/规则审批。
9. Event Arbiter 只能组合委员提供且能回指输入的证据，不得新增无来源事实。语义、事实和金融
   影响置信度分别保留；低置信、高分歧、数据陈旧、成本、OOD 或风险限制必须支持 abstain。
10. Model Council 只使用开发期 OOS 折；最终 holdout 继续 `LOCKED`。所有可比模型共享 split、
    成本、预算、种子和指标，不适用专家结构化 abstain，不能把不同目标的分数硬拼排名。
11. 历史回放使用一手、可追溯且具有机器可确定发布时间的内容及校验和固定的公共市场数据。
    没有真实 first-seen 历史归档时只验证 PIT 流程和前瞻风险语义，不声称因果或历史 Alpha。
12. 当前无 4070 Ti，故 P08 可以完成实现验证、CPU 资源上限、预算拒绝和模拟 OOM 恢复，但
    `P08-A07` 保持正式验收未完成。统一验收时必须在目标 GPU 实测；没有硬件就如实阻塞。
13. `LIVE_TRADING=false`、`live_trading_locked=true`、无真实账户、无秘密、无执行 adapter。
    P08 不生成 `ACCEPTANCE.md`，不启动 P09，延期状态继续遵循 ADR-0010。

## 后果

- 本地研究多一份 ledger/MLflow 双写与 reconciliation，但失败和中断不再从排行榜消失。
- 受限基础模型可能只显示不可用而没有分数，这是合规结果，不是需要伪造的缺口。
- 没有 GPU 时仍可验证安全、预算和恢复路径，但不能宣称满足 4070 Ti 实机上限。
- AI 委员会不具备自治执行能力；它的价值是形成有证据、可拒绝、可审计的提案。

## 外部契约依据

- MLflow Tracking Server：<https://mlflow.org/docs/latest/self-hosting/architecture/tracking-server/>
- MLflow Skinny：<https://pypi.org/project/mlflow-skinny/3.15.2/>
- MLflow Model Registry aliases：<https://mlflow.org/docs/latest/ml/model-registry/workflow/>
- Optuna 多进程存储：<https://optuna.readthedocs.io/en/stable/tutorial/10_key_features/004_distributed.html>
- PyTorch 可复现性：<https://docs.pytorch.org/docs/stable/notes/randomness.html>
- Chronos-2-small：<https://huggingface.co/autogluon/chronos-2-small>
- Moirai 2：<https://huggingface.co/Salesforce/moirai-2.0-R-small>
- TimesFM 3：<https://github.com/google-research/timesfm>
- Kronos：<https://github.com/shiyu-coder/Kronos>
- HKUDS/AI-Trader：<https://github.com/HKUDS/AI-Trader>
