# 安全政策

## P00/P01 边界

本阶段不连接真实交易账户、Testnet、交易所私有接口或任何需要身份凭据的服务。
项目只接受秘密的逻辑引用名称，不接受密码、Cookie、验证码、私钥、API Secret、
session 文件或提现凭据的值。聊天、源码、配置、报告、日志和 CI 工件都不能承载这
些值。

## Live 锁

`configs/base/runtime.toml`、`configs/exchanges/adapter_registry.json` 和
`aegisquant.bootstrap.live_lock` 共同构成阶段无关的 fail-closed 锁。任一配置请求 Live、
开启订单提交或注册实盘适配器，启动检查都必须失败。锁的演进只能通过后续任务书
规定的独立人工解锁流程，P01 不提供解锁函数。

P01 的 PostgreSQL 仅为监听 `127.0.0.1` 随机端口的一次性契约测试集群，不承载
真实数据，不安装服务，不保存密码。`AEGISQUANT_TEST_DATABASE_URL` 只在测试进程
生命周期内存在。

## 报告问题

发现安全问题时，只报告可复现条件和受影响边界；不要在 Issue、聊天或日志中粘贴
凭据。若值已泄露，应先在来源系统撤销或轮换，再记录不含秘密的事件时间线。
