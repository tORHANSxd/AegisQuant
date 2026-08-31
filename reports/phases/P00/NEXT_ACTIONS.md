# P00 后续动作

P00 到此停止，P01 未启动。下一阶段只能在用户明确授权并重新建立 P01 计划后执行。

在未来授权 P01 前，可由用户选择性确认以下非秘密信息；缺失时系统继续默认拒绝：

1. 是否接受本次 P00 验收和开放风险；
2. 若配置源码远程仓库，是否按 `docs/governance/BRANCH_PROTECTION.md` 启用主分支保护；
3. 本地只读数据路径、磁盘上限和 Windows/WSL/Docker/GPU 偏好；
4. 聚宽、X、Telegram、YouTube/GitHub、新闻订阅、Testnet 的权限状态与额度描述；
5. 风险偏好、允许市场、禁止资产和研究费用硬上限。

只应提供路径、状态、范围和限制，不能提供密码、Cookie、验证码、API Secret、私钥、
session 文件或 Token。上述信息不属于 P00 接受前置条件。
