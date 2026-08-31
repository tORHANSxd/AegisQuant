# Binance 订单簿恢复证据

固定 fixture 验证快照加增量、重复、迟到及 sequence gap。数量为绝对数量，零数量删除价位。

| 产品 | 处理序列 | 最终要求重建 |
|---|---|---|
| SPOT | APPLIED → DUPLICATE → LATE → GAP | True |
| USD_M | APPLIED → APPLIED → GAP | True |
