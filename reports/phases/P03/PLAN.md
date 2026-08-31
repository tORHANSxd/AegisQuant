# Phase P03 实施计划

- 规格版本：AegisQuant v3.1.0
- 阶段：P03 — Binance 公开市场数据、可回放数据集与 Silver 规范化
- 状态：`in_progress`
- 启动时间（UTC）：`2026-08-31T14:05:22.6917747Z`

## 不可突破的边界

1. `LIVE_TRADING` 必须保持锁定，订单提交必须保持关闭。
2. 只访问 Binance 官方公开市场数据端点；不得连接用户数据流、账户、订单或私有 API。
3. 不读取、索取或保存密码、Cookie、验证码、API Key、API Secret 或签名材料。
4. CI 必须完全离线，实时公开网络探测只能生成独立证据。
5. 真实连续运行不足 24 小时不得宣称通过 P03 连续流验收。
6. P03 未验收前不得开始 P04。

## 执行序列

1. 固化 P03 阶段需求追踪矩阵、官方 REST/WS 契约清单和 ADR。
2. 扩展 fail-closed provider/source policy 与公开行情适配器注册表。
3. 实现仅公开的 REST/WS 客户端、动态限流、检查点、历史下载和原始响应归档。
4. 实现 Spot 与 USDⓈ-M 盘口重建、缺口恢复、水位和连接健康状态。
5. 实现 instrument PIT 快照与 Kline、trade、book、mark/index、funding、OI Silver 模型。
6. 建立离线 fixture、确定性回放、质量规则、一致性检查和 Changelog watcher。
7. 对照本地 `nautilus-trader==1.231.0`，记录命名、路由、盘口和精度差异。
8. 运行格式、静态类型、单元、属性、混沌、集成、双 Python 及短时公共网络测试。
9. 启动真实 24 小时连续公开流验收；异常中断、休眠或无法解释的序列缺口均不得拼接通过。
10. 验收通过后生成全部 P03 证据、更新阶段状态、提交源码并执行一次本地 Git 归档。

## 验收策略

- CI：只读取提交的公开响应 fixture，不调用网络。
- 实时 smoke：显式访问 allowlist 内的公开 REST/WS，禁止凭据与重定向。
- 故障恢复：通过适配器级强制断开验证重连、REST 快照重建和水位恢复，不修改系统网卡。
- 24 小时 soak：使用哈希链和有界见证样本记录完整性；阶段在完成前保持 `in_progress`。

需求、实现、测试与证据的逐项映射见 `REQUIREMENTS_TRACEABILITY.csv`。
