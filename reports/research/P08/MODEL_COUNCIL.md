# P08 Model Council

Selected development candidate: `linear-fused`

| Model | Family | Modality | OOS loss | Net return | State |
|---|---|---|---:|---:|---|
| linear-market | LINEAR | MARKET_ONLY | 0.0005794961529427887751597959224 | 5.509 | EVALUATED |
| linear-event | LINEAR | EVENT_ONLY | 0.1768219928227334212651759858 | 5.509 | EVALUATED |
| linear-fused | LINEAR | FUSED | 6.25E-31 | 5.509 | EVALUATED |
| tree-lightgbm | LIGHTGBM | FUSED | 0.1750750973659817163736042775 | 5.509 | EVALUATED |
| tree-catboost | CATBOOST | FUSED | 0.1200797307344435544182714389 | 5.509 | EVALUATED |
| tree-xgboost | XGBOOST | FUSED | 0.08348058391634556132363376559 | 5.509 | EVALUATED |
| deep-tcn | TCN | FUSED | 0.802867533683865578913298346 | -5.511 | EVALUATED |
| deep-patch_transformer | PATCH_TRANSFORMER | FUSED | 0.006769243406507670553810965502 | 5.509 | EVALUATED |

All candidates share the same development OOS split, cost policy, search budget, and seed.

`complexity_privilege=false`; `final_holdout_opened=false`; no Alpha or production claim.
