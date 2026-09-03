# V5-P10 执行计划

1. 复用 P08 Event Increment、P09 Forecast Governance、现有 PortfolioProposal 与 RiskDecision。
2. 建立统一的 ExecutionCostModelV2、场景成本分布和版本化 Net Edge Policy。
3. 从相同概率场景重算 Net Edge，并逐项执行 Truth、Price-In、Uncertainty、OOD、Data Quality、
   Event Increment 和经济性 Gate。
4. 用 Forecast 内容派生 SignalId，强绑定 Portfolio proposal 与独立 Risk decision。
5. 输出互斥的 EventDirectionalAlpha、EventRiskOverlay 或第一类 NO_TRADE。
6. 生成 Schema、确定性证据、攻击测试、完整 CI 和冻结 Manifest；不打开 Final Holdout。
