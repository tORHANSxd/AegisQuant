# V5-P07 负结果与禁止外推

- 当前竞技场全部数据与指标是确定性 `DEVELOPMENT` fixture，没有从公网下载行情，也没有训练外部模型。
- TimesFM 2.5、Chronos-2、Moirai-2、Toto 2.0 只进入能力目录；依赖/adapter/许可或权重门禁未通过的
  候选被阻断，不能拿品牌名当性能证据。
- `multi-scale-patch-transformer-candidate` 的 `SIMULATED_OOM` 被保留为失败记录且不得参与 Champion 选择；
  这验证失败保存，不代表该模型在真实硬件一定 OOM。
- BTC/TREND/30m 由 TCN fixture 获胜、ETH/VOL_EXPANSION/4h 回退 linear baseline；这些预设 loss 只验证
  per-cell 选择和“无 universal model”规则，不是资产预测结论。
- 视觉消融的 Numeric+Vision 改善低于 `0.01` 门槛，因此返回 `VISION_NO_OOS_INCREMENT` 并淘汰视觉；
  该负结果是合约夹具，不推广到任何真实图像模型。
- Future availability、calibration/test 重叠、不等 OOS folds、capability hash splice 与 prediction artifact
  reuse 均 fail closed；这只证明防护路径，不证明数据源本身真实无泄漏。
- Final Holdout 没有打开，P08 事件增量没有执行，真实 OOS、Forward、成本后收益和准确率仍未知。
- 没有产生 Alpha Promotion、订单、真实账户连接或 Live trading 授权。
- 首轮完整 CI 并未通过：安全扫描误报 3 条内容哈希、P11 架构证据计数漂移，且 P15/三浏览器
  E2E 出现一次性失败。前两项已修复，后两项独立复跑及第二轮完整 CI 通过；该经历不应被删成
  “一次全绿”，也不构成模型有效性证据。

拿一组手填 loss 给模型颁“全市场冠军”奖杯，跟自己出题自己拿满分差不多。P07 只把考场规则钉死，
真正挨市场毒打得等真实 PIT 数据和后续门禁。
