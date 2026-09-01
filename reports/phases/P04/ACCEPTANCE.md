# P04 验收记录

## 决定

P04 验收通过。验收对象为实现提交
`2ad3f0ffdd76fba5e81ce9d12eb70bef31c2d84d`；23 项任务与 12 项验收要求共 35 项均为
`VERIFIED`，无 P04 豁免项。完整机器证据见 `CI_RESULTS.json`、`TEST_RESULTS.json` 与
`ARTIFACT_MANIFEST.json`。

## 阶段验收项

| 验收项 | 结果 | 核心证据 |
|---|---|---|
| P04-A01：同名 symbol 不错误合并经济暴露 | PASS | Canonical asset/pair/exposure 维度与场所 instrument ID 契约测试 |
| P04-A02：逆向合约 PnL 与数量单位正确 | PASS | 正向/逆向手算 Golden Case 与 Decimal 测试 |
| P04-A03：期权字段与 IV 来源明确 | PASS | expiry、strike、option type、settlement、IV source 跨所夹具测试 |
| P04-A04：每个 Adapter 有统一及场所特定测试 | PASS | OKX/Bybit/Deribit REST、WS、sequence、orderbook 契约测试 |
| P04-A05：Provider 断线不污染其他 Provider | PASS | 批次隔离、缺失场所和质量过滤测试 |
| P04-A06：跨所比较含时间、quote asset 与质量过滤 | PASS | ticker/funding/basis/OI/liquidity 对照与 lead-lag 测试 |
| P04-A07：社交源不可用明确降级且不影响账本 | PASS | `awaiting_credentials`/`degraded` 批次；事件流水线无账本依赖 |
| P04-A08：转载不计为独立证据 | PASS | URL/文本指纹、repost family 与独立证据计数测试 |
| P04-A09：删除修改传播至缓存与 Read Model | PASS | append-only revision、tombstone、projection 重放测试 |
| P04-A10：外部提示词不能调用工具或改配置 | PASS | 不可信文本标记、固定无工具/无配置权限安全测试 |
| P04-A11：当前互动数不进入历史特征 | PASS | engagement snapshot 按 available time 的 PIT 查询测试 |
| P04-A12：无凭据仍可验收且状态正确 | PASS | X/Telegram/YouTube fixtures 与 `awaiting_credentials` 测试 |

## 硬门

| 硬门 | 结果 | 说明 |
|---|---|---|
| 完整 CI | PASS | 20/20 门通过 |
| Python 3.13 | PASS | 219 passed，0 failed，0 skipped |
| Python 3.14.7 候选 | PASS | 183 passed，0 failed，0 skipped |
| 安全与供应链 | PASS | Bandit 0、秘密扫描 0、Python/JavaScript 依赖审计通过 |
| 公共只读边界 | PASS | 无认证、无 Cookie、无私有端点、无账户与订单能力 |
| `LIVE_TRADING` 锁 | PASS | 状态、适配器注册表与安全回归均保持锁定 |
| P03 豁免保持 | PASS | 未生成 `BINANCE_24H_SOAK.json`，ADR-0007 不变 |
| P05 阶段边界 | PASS | 未创建 P05 会计实现或阶段证据 |

## 限制

本验收证明离线契约、固定夹具、数据语义和安全边界，不证明凭据源已连通、特定地区可达、
生产采集 SLA 或真实交易能力。任何凭据接入、账户访问或交易能力都需要后续阶段的独立授权
与验收，不能消费本次结果当通行证。
