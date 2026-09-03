# AegisQuant v5.0 规格索引

- 当前 SSOT：`AegisQuant_v5.0_Truth_Causal_AI_Forecast_Codex_Master_Plan.md`
- 规格版本：`5.0`
- 规格日期：`2026-09-02`
- SHA-256：`aee366d5fa1a8ebd7449c597e6f822535546633efc335c1ab0053333d160a255`
- 总行数：2,799

## 全局主题

| 起始行 | 主题 |
|---:|---|
| 15 | 执行契约、SSOT 与禁止事项 |
| 108 | 当前必须修复的问题与 EvidenceTier |
| 197 | Truth Engine、证据图、时间语义与校准 |
| 724 | 事件理解、price-in 与反事实影响 |
| 1094 | Forecast Council、概率校准与可靠度衰减 |
| 1450 | Net Edge、风险、执行与研究协议 |
| 1872 | 数据库、API 与 Dashboard 契约 |
| 2008 | V5-P00 至 V5-P12 阶段计划 |
| 2313 | Promotion Gate、失败注入与最终成功标准 |

## 阶段索引

| 阶段 | 起始行 | 责任域 |
|---|---:|---|
| V5-P00 | 2012 | Evidence Reset 与 SSOT Migration |
| V5-P01 | 2039 | Truth contracts 与 temporal semantics |
| V5-P02 | 2058 | Source Registry、identity 与 C2PA |
| V5-P03 | 2078 | Evidence retrieval 与 independence graph |
| V5-P04 | 2105 | Truth Council 与 calibration |
| V5-P05 | 2125 | Event canonicalization、surprise 与 price-in |
| V5-P06 | 2143 | Event response dataset 与 causal layer |
| V5-P07 | 2163 | Forecast Council 2.0 |
| V5-P08 | 2186 | Truth-aware event counterfactual forecast |
| V5-P09 | 2206 | Meta-reasoner、skeptic、ensemble 与 conformal |
| V5-P10 | 2226 | Net Edge、portfolio 与 risk integration |
| V5-P11 | 2249 | Paper / Shadow forward proof |
| V5-P12 | 2282 | Testnet / Canary readiness |

## 历史实现基线

`AegisQuant_v3.1_Multimodal_Event_Intelligence_Codex_Master_Taskbook.md`、
`docs/spec/AegisQuant_Master_Taskbook_v3_1.md`、`state/PROJECT_PHASE_STATE.yaml` 和
`reports/phases/` 保留为 v3.1 历史实现及证据，不是当前 SSOT，也不自动具备 v5
Promotion 资格。

- 历史规格 SHA-256：`1265a4feeb126bf9004685b80c0aa01d053fd983079b80d5c9063abefc382d1f`
- 历史规格总行数：7,023
- 历史阶段范围：P00-P18

## 当前边界

`V5-P00` 至 `V5-P06` 已验收；`V5-P07` 正在实施，其后阶段仍未授权。P07 建立 Forecast Council
2.0 的统一张量、完整输出、能力矩阵、候选门禁与等折 OOS 竞技场。开发 fixture 上的 Truth、
Causal 与 Forecast 指标不得包装成真实世界准确率、因果效应或交易 Alpha。
