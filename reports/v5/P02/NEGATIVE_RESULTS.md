# V5-P02 负结果与禁止外推

- C2PA fixture 使用临时自建证书链，不是 C2PA 官方 conformance 认证或公共信任证明。
- 没有生产 trust-list 更新、OCSP、remote manifest、timestamp authority 或证书吊销运行证据。
- 没有真实来源历史准确率、纠错率、撤稿率、首报延迟或 compromised probability 校准。
- 没有真实世界事实核验准确率、Brier、ECE、retraction delay 或 calibration curve。
- 没有因果效应、预测准确率、净收益、回测或前瞻交易证据。
- 所有 P02 工件均不满足 Alpha Promotion；实盘、下单和真实账户连接继续关闭。

“验签成功，所以新闻是真的”属于密码学看了都想报警的逻辑飞跃，本阶段特意把这条歪路
焊死了。
