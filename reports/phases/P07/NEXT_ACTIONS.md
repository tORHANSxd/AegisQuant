# P07 后续动作

1. 保持 `LIVE_TRADING=true` 锁定语义，不连接真实账户，不开启最终 holdout。
2. 按 ADR-0010 等待项目业主在全部工程完成后显式发起统一正式验收；届时重新运行仍适用门禁，
   再生成 `ACCEPTANCE.md` 和真实验收时间。
3. 如需比较旧 R331，由用户提供原始文件、SHA-256、数据/成本口径和权利状态；只能通过
   content-addressed 外部基准注册，不回填或覆盖内部实验。
4. P08 若获明确启动，应复用 P07 的八类 Manifest、实验账本语义、公平比较预算和最终 holdout
   锁；不得把 MLflow/Optuna/复杂模型接入当作绕过 P07 统计门禁的后门。
5. 后续依赖升级时重跑 Python 3.13/3.14、scikit-learn 数值契约及 Pandas/Nautilus 弃用检查。

本报告只列后续动作，不表示已启动 P08。
