# P13-process-drill Postmortem

## Impact

仅在 P13 模拟运行时注入故障；新增风险被阻断，真实资金与交易账户未受影响。

## Root cause

确定性注入 `PROCESS`，用于验证安全状态与恢复契约。

## Recovery

检查点、幂等、重复事实和对账证据通过后恢复到原非资金模式。
