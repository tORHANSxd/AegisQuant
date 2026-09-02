# P15 后续动作

1. 完成 P15 证据提交和本地归档后，才可把阶段状态切换到 P16；不得在本次 P15 收口提交中夹带
   Prometheus、Grafana、Loki、部署、备份或身份实现。
2. P16 优先建立可观测性、告警路由、审计写入、成熟身份、最小权限、部署与灾备契约；在这些边界
   完成前，工作台继续限制为 loopback VIEWER，不得公开部署。
3. 为后续策略和订单定义可核验的 signal、event、model、risk、order、fill、ledger 实体关联；缺失
   证据时继续使用 `NOT_AVAILABLE`/`NOT_APPLICABLE`，禁止按时间邻近补造因果链。
4. 继续以仓库内 Node 24.20.0 与 pnpm 11.24.0 直接运行前端门禁；若调整根脚本或 CI 启动方式，
   必须保留防递归 PATH 漂移测试。
5. 在最终统一验收阶段由业主决定是否恢复延期的阶段验收；恢复前不创建 12h/24h 后台任务，也不
   生成 P15 `ACCEPTANCE.md`。
6. 继续保持 `LIVE_TRADING=false`，不连接真实交易账户，不索取或写入明文密码、Cookie、验证码或
   API Secret，不执行真实或 Testnet 场所订单请求。
