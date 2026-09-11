# B7 一次性留出与交付契约

`python -m scripts.run_alpha_v5_final_holdout --config configs/research/alpha_v5_final_holdout_contract.yaml --preflight-dir <已核验目录>` 只生成一次封存的协议、资格状态及 B0–B7 交付索引。配置中的真实数据、项目锚点、冻结候选和数据访问授权都必须为 null，五项真实研究/交易预算均为 0。现有已用源的尾部不是最终留出；本批不创建任何真实留出登记。

`open_persistent_holdout` 复用原一次性 claim 和 `FinalHoldoutVault`。它现在要求额外的 `HoldoutAccessAuthorization`；旧的任意目录调用不再有资格读取真实最终数据。`directory` 仅记录候选输出位置，访问状态固定为项目根目录下的 `state/final_holdout_anchor.json`、`state/final_holdout_access_claim.json` 与 `state/final_holdout_access_events.jsonl`。同一个项目、候选、路径、符号链接、重命名和 generation 不能生成第二个 claim。项目根由实现位置确定，生产 API 不接受 root override。

未来真实登记必须经过独立审查和明确授权：锚点绑定语义数据 ID、原始 bytes 的 SHA256/长度、完整连续日期、源材料边界、完整来源/派生 hash、未使用证明、冻结候选、操作授权、日志 genesis 和独立不可回滚存储证明。哈希及 metadata 的一致性不等于来源事实已获独立查证。缺失、未知、已用源文件、尾部越界、覆盖不足或授权不匹配均在内容读取前拒绝。日志必须预先存在且与锚点 genesis 一致，程序不会创建一个空日志恢复访问次数。

所有访问共享固定 OS exclusive lock 与原子 claim，claim 写入后 flush/fsync，随后才从登记的唯一源文件读取和校验完整 bytes，再交给 `loader(data: bytes)` 冻结解析器。解析失败、数据文件读取异常、hash/长度不符均消耗 claim。锁只协调并发，不是另一个访问计数器；异常退出遗留锁必须先独立审查，程序不自动清除。成功日志可证明已消费，单独删除 claim 文件也不能恢复访问。删除或回滚全部本地证据不是应用代码能解决的威胁，真实运行必须有独立不可回滚存储与 OS 访问权限。

`holdout_read_firewall` 必须在文件句柄产生前启用，保护声明源、别名/派生路径及文件身份，识别普通路径、symlink 和 hardlink 读取；只有 claim 内的原始 bytes 读取拥有短暂许可，解析器不能再次打开源文件。开发加载器 `checked_development_path` 对已登记锚点强制 hash pin 和完整传递血缘，禁止复制缓存、预览结果或特征中的最终留出来源。未知血缘不能默认视为安全。该 Python 守卫不提供 OS 沙箱保证；不得把受保护路径或旧句柄交给绕过 Python audit 的原生扩展。

`ResearchFreezeManifest.admission_extension` 为版本化扩展；旧哈希/序列化保持不变。新真实访问必须另外冻结风险、规则、容量、统计定义、比较族、完整试验史、数据血缘、模型权重、测试期定期更新程序与独立预审。没有登记更新程序就不能在测试期重训。所有原门槛和共同风险/执行/资金约束保留。

`independent_review_handoff` 只使用现有 `PromotionDecision` 的 HOLD/REJECT。即使全部门槛和最终 immutable report 都已提供，也只返回 `INDEPENDENT_REVIEW_REQUIRED`，不切换模型 alias，不开启 ML、纸面或订单。本批独立实证准入评审是 NOT_COLLECTED，`NO_PROVEN_ALPHA / CASH` 继续有效。

当前工程交付不代表完整研究验收完成。后续需要真实 PIT、历史费用/规则/盘口/延迟、共享现金回放、成熟基础机会和全试验史、后批真实运行/拟合授权，以及已证明未使用至少十二个月的数据。失败和不确定结果不得删除或通过新 generation 规避。
