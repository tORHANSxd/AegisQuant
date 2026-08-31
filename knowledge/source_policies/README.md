# 来源处理政策

任何外部内容在采集、归档或送入模型前都必须有通过 JSON Schema 校验的
`SourceProcessingPolicy`。未登记、条款版本未知或审批状态不明确时使用
`configs/data_sources/default_deny_policy.json`，这意味着所有处理边界都拒绝。

P00 没有启用采集器，也没有批准任何外部平台内容。公开网页可供人工核对工程版本，
但版本研究不构成市场内容采集许可。
