# Framework Review

评审基于 2026-09-02 读取的官方稳定文档或项目主仓库元数据；未安装、导入或执行新框架。

| Framework | Observed contract | Decision | Reason |
|---|---|---|---|
| [NautilusTrader](https://nautilustrader.io/docs/) | 事件驱动、统一研究/仿真/实盘语义、模块化 Adapter 和显式恢复。 | `retain_pinned_runtime` | 项目继续锁定已通过契约的 GA 1.231.0；官方 Python API 的 2.0.0rc3 属预发布，不升级。 |
| [QuantConnect LEAN](https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/overview) | Universe→Alpha/Insight→Portfolio Construction→Risk→Execution 的模块边界。 | `reference_only` | 吸收关注点分离；C# 内核与 Python 3.11 桥接不作为本项目依赖。 |
| [Microsoft Qlib](https://qlib.readthedocs.io/en/latest/component/strategy.html) | 预测信号、组合策略、工作流和回测松耦合。 | `reference_only` | 吸收实验/信号/组合分层；不引入新的数据语义或运行时依赖。 |
| [VeighNa](https://www.vnpy.com/docs/cn/index.html) | CTA、组合、价差、期权、算法执行与回测模块化。 | `reference_only` | 吸收国内平台 API 识别词典和模块分类，不加载策略或交易接口。 |
| [Hummingbot](https://hummingbot.org/strategies/v2-strategies/) | V2 Controller 产生 ExecutorAction，Executor 管理有限订单生命周期。 | `reference_only` | 吸收 Controller/Executor 分离；Dashboard 已标记不再积极维护，不作为产品底座。 |
| [Freqtrade/FreqUI](https://docs.freqtrade.io/en/stable/backtesting/) | 加密回测、Dry Run、lookahead-analysis 和 recursive-analysis。 | `reference_only` | 吸收前视/递归偏差检查；其全量 DataFrame 回测语义必须由 AegisQuant PIT 门禁复核。 |
| [OpenBB Workspace](https://docs.openbb.co/workspace) | Widget 元数据把后端 API 映射为可组合研究工作区。 | `design_reference` | 仅吸收可组合工作区和元数据思想，P09 不实现看板或复制视觉资产。 |
| [Grafana](https://grafana.com/docs/grafana/latest/administration/provisioning/) | 数据源和 Dashboard 可通过版本化文件配置。 | `defer_to_p16` | 作为运维可观测性而非主业务看板；P09 只记录评审。 |
| [HKUDS/AI-Trader](https://github.com/HKUDS/AI-Trader) | README/OpenAPI 展示 FastAPI/React、Agent 注册、信号市场与复制交易接口。 | `metadata_only_reject_active_integration` | 未观察到根许可证文件；不调用 Skill、注册、外部 API、信号发布或复制交易，只借鉴显式 API 契约和前后台任务隔离。 |

AI-Trader 固定观察 revision：`d03ff6c056b32ced735adf7c19ed8175adb1c8df`。根许可证文件未观察到，故权利为 `unknown`；
其 Agent 注册、信号发布、复制交易和生产 API 与 AegisQuant 安全边界冲突，未接入。
