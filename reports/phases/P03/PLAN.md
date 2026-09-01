# Phase P03 实施计划

- 规格版本：AegisQuant v3.1.0
- 阶段：P03 — Binance 公开市场数据、可回放数据集与 Silver 规范化
- 状态：`accepted_with_waiver`
- 启动时间（UTC）：`2026-08-31T14:05:22.6917747Z`
- 关闭时间（UTC）：`2026-09-01T03:18:27.452548Z`
- 验收豁免：`P03-WAIVER-001`（仅 `P03-A01`）

## 不可突破的边界

1. `LIVE_TRADING` 必须保持锁定，订单提交必须保持关闭。
2. 只访问 Binance 官方公开市场数据端点；不得连接用户数据流、账户、订单或私有 API。
3. 不读取、索取或保存密码、Cookie、验证码、API Key、API Secret 或签名材料。
4. CI 必须完全离线，实时公开网络探测只能生成独立证据。
5. 真实连续运行不足 24 小时不得宣称通过 P03 连续流验收；业主豁免只能记为 `waived`。
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
9. 已发起真实连续公开流验收；两次尝试均未形成合格证据。业主明确豁免该项，详见
   `ADR-0007` 与 `BINANCE_SOAK_ATTEMPT_SUMMARY.json`。
10. 以 `accepted_with_waiver` 生成全部 P03 证据、更新阶段状态、提交源码并执行一次本地
    Git 归档。

## 验收策略

- CI：只读取提交的公开响应 fixture，不调用网络。
- 实时 smoke：显式访问 allowlist 内的公开 REST/WS，禁止凭据与重定向。
- 故障恢复：通过适配器级强制断开验证重连、REST 快照重建和水位恢复，不修改系统网卡。
- 24 小时 soak：没有通过；`P03-A01=waived`，禁止创建或声称存在合格 24 小时证据。

## 规格偏差

项目业主明确取消 `P03-A01` 的 24 小时验收。该偏差没有降低任何代码、安全或离线测试
门禁，只移除了长时运行这一项的强制完成条件。P03 因此不是无条件验收，而是带一个可审计
豁免关闭；残余风险继续开放。

需求、实现、测试与证据的逐项映射见 `REQUIREMENTS_TRACEABILITY.csv`。
