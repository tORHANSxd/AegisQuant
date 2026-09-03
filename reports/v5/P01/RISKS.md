# V5-P01 风险

1. **合约不等于模型。** 当前概率字段只有类型和边界，不具备真实校准含义。缓解：状态
   固定为 `CONTRACTS_IMPLEMENTED_UNCALIBRATED`，禁止 Promotion。
2. **同源识别仍依赖上游 identity。** P01 只按 `independence_group` 保守计数；真实所有权、
   转载链和来源可靠度属于 P02/P03。缺失组一律并入同一未知组，宁可少算。
3. **SourceIdentity 是破坏性 schema 变更。** 新增必需 `available_time` 后版本升级到
   `2.0.0` 且 compatibility=`NONE`，旧 v1 schema 保留，不伪装兼容。
4. **QUOTE 与真实性判定不是一个维度。** Claim 类型保留规格原词 `QUOTE`，评估 scope
   使用 `QUOTE_AUTHENTICITY`，防止把“确有其言”误写成“内容为真”。
5. **没有真实来源准确率。** 本阶段只有固定时钟 DEVELOPMENT 证据；外部事实获取、
   标注、校准和 OOS 验证尚未开始。
6. **源仓库 HEAD 只是历史基线。** 工作区采用内容寻址 manifest 绑定全部改动，
   `implementation_commit` 明示为 `SOURCE_REPOSITORY_BASELINE_ONLY`，不能单靠该 commit
   重建 P01；项目级本地 Git 存档负责保存完整工作区快照。
