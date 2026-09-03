# V5-P04 负结果与禁止外推

- 58 个 claim/label 全部是确定性 DEVELOPMENT fixture，不是网络抓取或人工核验语料。
- Gradient Boosting 在 validation Brier 上胜出不代表它在真实来源、语言或事件类型上更好。
- 预先指定 Platt 的 test Brier 为 `0.128671182730271`，但 isotonic 在同一小 test 上得到更低
  Brier；不得事后改选 isotonic，否则就是 test leakage。
- 四个 calibration strata 的 test 样本均很少，部分没有类别变化，切片 slope/intercept 不足。
- source reliability 从 `0.9` 降到 `0.8235` 只是政策负控，不是任何真实媒体评分。
- 未执行真实世界 truth precision/recall、retraction delay、跨语言校准或长期 drift 评估。
- 未实现 P05 event surprise、P06 causal effect、P07 forecast foundation model 或 P08 event
  increment。
- 未产生 market forecast accuracy、净收益、真实回测或 forward trading evidence。
- 所有 P04 工件均不满足 Alpha Promotion；实盘、下单和真实账户连接继续关闭。
- P00–P03 manifest 的固定 SHA、state 和测试仍位于同一可写工作树；内部自洽检查能防误改，
  不能替代受保护远端、外部签名或透明日志。故本阶段不声称“不可篡改历史”。
- 完整 CI 同时承担 deterministic evidence build 与 verification，部分 legacy 工件带运行时间戳；
  P04 的最终 manifest 必须在这些生成步骤完成后再封存并单独执行 `--check`。
- 输入快照已对回 claim 与 evidence revision 的实际 content hash，但其他 consistency/
  manipulation 派生工件仍只有内容地址引用；本阶段没有受保护 artifact registry 的存在性证明。
- 全量 pytest 与 Python 3.14 candidate 各报告 11 条第三方弃用 warning，涉及 Starlette/httpx、
  Nautilus/NumPy timedelta 与 pandas；本轮无测试失败，但后续依赖升级前需消除这些兼容债务。

拿 58 条自编题考自己，再宣布“事实判断准确”，这不叫 AI 进化，叫开卷考试还自己批卷。
P04 只把考场隔离规则搭牢，真实成绩后面拿公开数据说话。
