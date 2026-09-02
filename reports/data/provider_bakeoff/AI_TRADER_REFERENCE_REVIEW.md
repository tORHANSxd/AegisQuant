# HKUDS/AI-Trader 参考复核

- 复核日期：2026-09-02
- 官方仓库：https://github.com/HKUDS/AI-Trader
- 使用方式：`REFERENCE_ONLY`
- 外部脚本执行：0
- 外部 Skill 加载：0
- 平台注册：0
- 代码复制：0
- 真实账户或 Live 连接：0

## 可借鉴的高层思想

1. Paper 环境先于真实交易，且实验/挑战应保留暴露和结果记录。
2. Web 服务与后台 worker 分离，避免研究任务阻塞用户接口。
3. 信号、讨论、实验和表现应有可追踪实体，而不是只留一条收益截图。

这些思想已经由 AegisQuant 自身的 Paper/Shadow、事件溯源、实验账本、运行监督和只读工作台契约实现；
没有复制 AI-Trader 代码，也没有把它变成运行时依赖。

## 明确拒绝的边界

- 不执行 README 中“一条消息读取远程 Skill 并注册平台”的流程。
- 不启用 copy trading、broker sync、agent direct trading 或任何 Live 自动化。
- 不把社区排名、Star、宣传收益或 mark-to-market 排名当成策略有效性证据。
- 不向第三方上传本项目数据、账户信息、策略、密钥或研究结果。

## 许可证结论

README 徽章声称 MIT，但复核时仓库根目录没有可读取的 `LICENSE` 文件，对应 raw URL 返回 404。
因此许可证不能仅凭徽章视为已核验：本阶段只保留思想级引用，不复制或派生其代码。若未来出现精确
代码复用需求，必须先固定 commit、取得完整许可证文本并完成依赖与安全审计。
