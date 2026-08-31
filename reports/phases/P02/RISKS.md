# P02 开放风险

以下风险不阻断 P02，但它们明确限制“已经验证”的边界。拿 9.55 MiB 热样本外推结果冒充
200 GiB 生产 SLA，那不是性能工程，是给数字化妆。

| ID | 级别 | 风险 | 当前约束 |
|---|---|---|---|
| P02-RISK-001 | medium | PyArrow stubs 面向 API 20，runtime 为 25.0.1 | 窄适配；Pyright strict；双 Python Arrow/Parquet 契约持续阻断升级 |
| P02-RISK-002 | medium | 本机可用空间低于 200 GiB 湖建议的 500 GiB | 不生成 100/200 GiB 文件；只保留显式线性估算；真实规模另机复测 |
| P02-RISK-003 | low | 用户未授权真实资产路径 | 仅扫描 4,096 文件合成夹具；未来必须获得精确路径的只读授权 |
| P02-RISK-004 | low | 公开兼容样本依赖远程 GitHub 对象 | 固定 commit、SHA-256、Git blob SHA-1；禁止静默替换 |
| P02-RISK-005 | medium | 未配置独立备份目的地 | 当前只有恢复顺序和容量策略；生产耐久性声明前必须完成备份/恢复演练 |

继承风险仍包括 NautilusTrader Beta/Windows 支持边界、pandas UTC 弃用提示、远程
GitHub Actions 尚未执行、一次性 PostgreSQL trust 测试边界和 host Node 版本差异。机器
可读全集位于 `state/OPEN_RISKS.yaml`。若不可变性、PIT、质量隔离、来源政策、加密、
扫描只读性或 Live 锁任一失败，阶段必须降级，不得带病进入后续阶段。
