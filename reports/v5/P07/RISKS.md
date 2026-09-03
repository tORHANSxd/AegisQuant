# V5-P07 风险

1. **能力目录不是可运行环境。** Foundation/deep/vision 候选多数只记录 adapter、依赖和许可状态；
   catalog membership 绝不证明模型已安装、权重可信或输出正确。
2. **确定性 OOS 指标不是真实 OOS。** 当前 loss、方向准确率、CRPS、Brier、coverage、tail recall 与
   成本后收益均为契约夹具，只证明聚合和选择逻辑。
3. **等折比较仍依赖上游数据。** split、dataset、calibration 与 prediction hash 防止普通拼接，但
   无法单独证明外部文件内容、交易所历史或 corporate-action/universe 事实完整。
4. **单一 primary loss 会压扁多目标。** 真实竞技必须联合报告方向校准、CRPS、pinball、Brier、
   interval coverage、tail recall、净收益、回撤、换手、容量与成本，不能靠一个排名拍脑袋。
5. **Regime 标签可能漂移。** Champion 按 regime 分桶不代表 regime 检测可靠；UNKNOWN/OOD 必须允许
   abstain，且 forward degradation 需要降权或退役。
6. **校准方法依赖时序假设。** Adaptive conformal 也不能机械假设静态 exchangeability；真实阶段需
   监测 coverage、undercoverage 与 calibration drift。
7. **模型许可会变。** 当前许可状态必须在下载/训练/部署前再次验证；未知、禁止或 research-only
   许可不得偷渡为生产能力。
8. **资源门禁只约束声明预算。** 实际 GPU/CPU/RAM/latency 需由受控执行器测量并与 artifact 绑定。
9. **视觉增量容易过拟合。** Chart/heatmap 渲染必须 PIT；若三方消融没有稳定 OOS 增量就删除视觉支路。
10. **工作树 Manifest 不是外部不可篡改锚。** 内容寻址和状态交叉绑定可发现漂移，但不替代签名、
    受保护远端或透明日志。
11. **没有交易证据。** Final Holdout、Paper、Shadow、Testnet、成本压力、容量与真实公网准确率均未完成。
12. **Windows 工具链仍可能瞬态抖动。** 首轮 CI 曾出现一次 Polars CPU flag 读取和 Web E2E 失败；
    当前包版本/运行时/CPU 特征一致，P15、三浏览器 E2E 与第二轮完整 CI 均通过，但后续仍应保留
    完整失败日志并禁止用 `POLARS_SKIP_CPU_CHECK` 绕过真实兼容性检查。
