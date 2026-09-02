import Link from "next/link";
import type { UTCTimestamp } from "lightweight-charts";
import type { ReactNode } from "react";

import type { WorkbenchResponse } from "../generated/client";
import {
  DataQualityGrid,
  IncidentTimeline,
  MetricTile,
  RiskStateBanner,
  SignalDecisionTrace,
  StatusBadge,
  VirtualDataTable,
} from "./common";
import {
  AttributionWaterfall,
  CandlestickTradeChart,
  EquityChart,
  PnLHeatmap,
} from "./charts/chart-suite";
import { DataState } from "./data-state";

export type WorkspacePageKey =
  | "overview"
  | "live"
  | "performance"
  | "execution"
  | "strategies"
  | "models"
  | "market"
  | "intelligence"
  | "risk"
  | "research"
  | "research-intelligence"
  | "data"
  | "incidents"
  | "system";

export interface WorkspaceFilters {
  account: "paper-account";
  currency: "USDT";
  range: "1D" | "7D" | "30D" | "ALL";
  timezone: "Asia/Shanghai" | "UTC";
  strategy: "all" | "p06-buy-hold" | "strategy-core";
  venue: "all" | "SIM" | "BINANCE-TESTNET";
}

type SearchValues = Record<string, string | string[] | undefined>;

export function resolveWorkspaceFilters(values: SearchValues): WorkspaceFilters {
  const scalar = (key: string) => {
    const value = values[key];
    return Array.isArray(value) ? value[0] : value;
  };
  const range = scalar("range");
  const timezone = scalar("timezone");
  const strategy = scalar("strategy");
  const venue = scalar("venue");
  return {
    account: "paper-account",
    currency: "USDT",
    range: range === "1D" || range === "7D" || range === "30D" ? range : "ALL",
    timezone: timezone === "UTC" ? "UTC" : "Asia/Shanghai",
    strategy: strategy === "p06-buy-hold" || strategy === "strategy-core" ? strategy : "all",
    venue: venue === "SIM" || venue === "BINANCE-TESTNET" ? venue : "all",
  };
}

const pages: Record<WorkspacePageKey, { eyebrow: string; title: string; description: string }> = {
  overview: {
    eyebrow: "PORTFOLIO COMMAND CENTER",
    title: "账户与风险总览",
    description: "在五秒内判断账户、损益、风险、订单与对账状态；所有数值来自同一历史开发快照。",
  },
  live: {
    eyebrow: "POINT-IN-TIME OPERATIONS",
    title: "实时台与状态回放",
    description: "当前是可回放的历史开发快照；账户、风险、订单和对账来自同一服务端水位。",
  },
  performance: {
    eyebrow: "PERFORMANCE & ATTRIBUTION",
    title: "绩效、成本与归因",
    description: "每个损益数字都附公式、来源和截至时间；不把开发回测冒充实盘收益。",
  },
  execution: {
    eyebrow: "EXECUTION FORENSICS",
    title: "执行质量与订单追溯",
    description: "逐订单追踪决策链，并将实际历史 K 线与时间对齐的归一化报价/虚拟成交分开标识。",
  },
  strategies: {
    eyebrow: "STRATEGY REGISTRY",
    title: "策略目录与信号",
    description: "展示研究阶段策略、版本、信号和失败边界；没有网页参数热改或发布入口。",
  },
  models: {
    eyebrow: "MODEL GOVERNANCE",
    title: "模型评估与治理",
    description: "模型候选按同一数据切分和成本预算比较；最终 Holdout 仍保持关闭。",
  },
  market: {
    eyebrow: "MARKET CONTEXT",
    title: "市场状态与历史回放",
    description: "公开历史 K 线、公开衍生品帧和归一化报价回放均明确区分，不提供买卖建议。",
  },
  intelligence: {
    eyebrow: "MULTIMODAL EVENT INTELLIGENCE",
    title: "全球事件与叙事情报",
    description: "事件、证据、叙事、来源政策、历史回放和风险告警来自同一只读快照。",
  },
  risk: {
    eyebrow: "INDEPENDENT RISK",
    title: "风险限额与熔断姿态",
    description: "限额为签名策略中的示例开发值，仅查看余量和原因，不允许在网页修改。",
  },
  research: {
    eyebrow: "RESEARCH FACTORY",
    title: "研究运行与负结果",
    description: "成功、失败和错误运行一并保留；选择不按单一 Sharpe 或营销式最优排序。",
  },
  "research-intelligence": {
    eyebrow: "KNOWLEDGE INTELLIGENCE",
    title: "外部知识与情报研究",
    description: "来源政策、证据关系和可复现实验并列展示；外部内容始终按不可信数据处理。",
  },
  data: {
    eyebrow: "DATA CONTROL PLANE",
    title: "数据质量、来源与血缘",
    description: "查看来源状态、缺口、策略处置和内容哈希，不允许浏览器直连核心数据库。",
  },
  incidents: {
    eyebrow: "INCIDENT COMMAND",
    title: "事故时间线与恢复证据",
    description: "展示 P13 故障演练的检测、风险收缩、恢复与对账证据；未影响真实资金。",
  },
  system: {
    eyebrow: "SYSTEM READINESS",
    title: "系统健康与契约状态",
    description: "这里只展示历史 CI 与快照健康，不伪装成 P16 可观测性或生产探针。",
  },
};

const money = new Intl.NumberFormat("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const percent = new Intl.NumberFormat("zh-CN", { style: "percent", minimumFractionDigits: 2, maximumFractionDigits: 2 });
const decimal = new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 6 });

function formatTime(value: string, timezone: WorkspaceFilters["timezone"]): string {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "medium",
    timeZone: timezone,
  }).format(new Date(value));
}

function rangePoints(
  points: Array<{ time: string; value: string }>,
  range: WorkspaceFilters["range"],
): Array<{ label: string; value: number }> {
  if (range === "ALL" || points.length < 2) {
    return points.map((point) => ({ label: point.time, value: Number(point.value) }));
  }
  const days = range === "1D" ? 1 : range === "7D" ? 7 : 30;
  const latest = Math.max(...points.map((point) => Date.parse(point.time)));
  const cutoff = latest - days * 86_400_000;
  return points
    .filter((point) => Date.parse(point.time) >= cutoff)
    .map((point) => ({ label: point.time, value: Number(point.value) }));
}

function MetricGrid({ children }: Readonly<{ children: ReactNode }>) {
  return <section className="metric-grid" aria-label="页面核心指标">{children}</section>;
}

function Surface({
  kicker,
  title,
  aside,
  children,
  wide = false,
}: Readonly<{
  kicker: string;
  title: string;
  aside?: ReactNode;
  children: ReactNode;
  wide?: boolean;
}>) {
  return (
    <article className={`surface${wide ? " wide" : ""}`}>
      <div className="surface-heading">
        <div><p className="section-kicker">{kicker}</p><h2>{title}</h2></div>
        {aside}
      </div>
      {children}
    </article>
  );
}

function FormulaNote({ data }: Readonly<{ data: WorkbenchResponse }>) {
  const attribution = data.pnl_attribution.payload;
  return (
    <details className="formula-note" open>
      <summary>净损益口径与来源</summary>
      <code>{attribution.formula}</code>
      <p>
        来源 <strong>{data.pnl_attribution.source_artifact}</strong> · 截至 {data.pnl_attribution.as_of_time} ·
        计价 {attribution.reporting_asset_id} · {attribution.source_scope}
      </p>
    </details>
  );
}

function LiveView({ data, filters }: Readonly<{ data: WorkbenchResponse; filters: WorkspaceFilters }>) {
  const account = data.account.payload;
  const pnl = data.pnl.payload;
  const risk = data.risk.payload;
  const points = rangePoints(account.equity_curve, filters.range).map((point) => ({
    label: formatTime(point.label, filters.timezone), value: point.value,
  }));
  const orders = data.orders.filter((item) =>
    (filters.strategy === "all" || item.payload.strategy_id === filters.strategy)
    && (filters.venue === "all" || item.payload.venue_id === filters.venue));
  return <>
    <MetricGrid>
      <MetricTile label="账户权益" value={money.format(Number(account.equity))} unit={account.reporting_asset_id} detail="历史开发快照" />
      <MetricTile label="当日净损益" value={money.format(Number(pnl.net))} unit={pnl.reporting_asset_id} detail="含费用与资金费" />
      <MetricTile label="风险状态" value={risk.state} detail={risk.reason_codes.join(" · ")} />
      <MetricTile label="对账状态" value={data.reconciliation.payload.state} detail={`序列 ${data.reconciliation.payload.last_sequence}`} />
    </MetricGrid>
    <RiskStateBanner state={risk.state} reasons={[...risk.reason_codes]} />
    <section className="dashboard-grid">
      <Surface kicker="EQUITY REPLAY" title={`权益轨迹 · ${filters.range}`} wide><EquityChart points={points} /></Surface>
      <Surface kicker="POINT-IN-TIME" title="账户事实">
        <dl className="fact-list">
          <div><dt>现金</dt><dd>{money.format(Number(account.cash))} {account.reporting_asset_id}</dd></div>
          <div><dt>持仓</dt><dd>{data.positions.length}</dd></div>
          <div><dt>订单</dt><dd>{orders.length}</dd></div>
          <div><dt>未知订单</dt><dd>{account.unknown_order_count}</dd></div>
          <div><dt>最近对账</dt><dd>{formatTime(account.last_reconciliation_at, filters.timezone)}</dd></div>
        </dl>
      </Surface>
    </section>
    <Surface kicker="DATA & RECONCILIATION" title="数据与对账一眼判断">
      <DataQualityGrid items={[
        ...data.data_health.map((item) => ({ id: item.entity_id, label: item.payload.provider_id, state: item.payload.state, reason: item.payload.reason_codes.join(" · ") })),
        { id: "reconciliation", label: data.reconciliation.payload.venue_id, state: data.reconciliation.payload.state === "SYNCHRONIZED" ? "READY" : "DEGRADED", reason: data.reconciliation.payload.reason_codes.join(" · ") },
      ]} />
    </Surface>
  </>;
}

function OverviewView({ data, filters }: Readonly<{ data: WorkbenchResponse; filters: WorkspaceFilters }>) {
  return <>
    <LiveView data={data} filters={filters} />
    <FormulaNote data={data} />
    <Surface kicker="VISIBLE ORDER TRACEABILITY" title="可见订单追溯入口">
      <div className="table-scroll"><table><thead><tr><th>订单</th><th>策略</th><th>标的</th><th>状态</th><th>完整链</th></tr></thead><tbody>
        {data.orders.map((order) => <tr key={order.entity_id}><td>{order.payload.order_id}</td><td>{order.payload.strategy_id}</td><td>{order.payload.instrument_id}</td><td>{order.payload.status}</td><td><Link className="trace-link" href={`/execution/orders/${encodeURIComponent(order.entity_id)}`}>信号 → 账本</Link></td></tr>)}
      </tbody></table></div>
    </Surface>
  </>;
}

function PerformanceView({ data, filters }: Readonly<{ data: WorkbenchResponse; filters: WorkspaceFilters }>) {
  const item = data.pnl_attribution.payload;
  const strategy = data.strategies[0]?.payload;
  const equity = rangePoints(data.account.payload.equity_curve, filters.range).map((point) => ({
    label: formatTime(point.label, filters.timezone), value: point.value,
  }));
  const pnl = rangePoints(data.pnl.payload.pnl_curve, filters.range).map((point) => ({
    label: formatTime(point.label, filters.timezone), value: point.value,
  }));
  const contributions = [
    { label: "交易毛损益", value: Number(item.gross_trading_pnl) },
    { label: "手续费", value: -Number(item.trading_fees) },
    { label: "点差", value: -Number(item.spread_cost) },
    { label: "滑点", value: -Number(item.slippage_cost) },
    { label: "冲击", value: -Number(item.impact_cost) },
    { label: "资金费", value: Number(item.funding) },
    { label: "借贷利息", value: -Number(item.borrow_interest) },
  ];
  return <>
    <MetricGrid>
      <MetricTile label="交易毛损益" value={money.format(Number(item.gross_trading_pnl))} unit={item.reporting_asset_id} detail="服务端归因" />
      <MetricTile label="净损益" value={money.format(Number(item.net_pnl))} unit={item.reporting_asset_id} detail="按下方公式" />
      <MetricTile label="最大回撤" value={strategy ? percent.format(Number(strategy.maximum_drawdown)) : "不可用"} detail="P06 回测口径" />
      <MetricTile label="换手" value={strategy ? decimal.format(Number(strategy.turnover)) : "不可用"} detail="未声称生产容量" />
    </MetricGrid>
    <FormulaNote data={data} />
    <section className="dashboard-grid">
      <Surface kicker="EQUITY" title="权益曲线"><EquityChart points={equity} /></Surface>
      <Surface kicker="GROSS TO NET" title="毛到净归因"><AttributionWaterfall points={contributions} /></Surface>
    </section>
    <Surface kicker="P&L DISTRIBUTION" title="损益时序"><PnLHeatmap points={pnl} /></Surface>
  </>;
}

function ExecutionView({ data, filters }: Readonly<{ data: WorkbenchResponse; filters: WorkspaceFilters }>) {
  const quality = data.execution_quality[0]?.payload;
  const replay = data.market.find((item) => item.payload.data_kind === "NORMALIZED_QUOTE_REPLAY");
  const orders = data.orders.filter((item) =>
    (filters.strategy === "all" || item.payload.strategy_id === filters.strategy)
    && (filters.venue === "all" || item.payload.venue_id === filters.venue));
  return <>
    <MetricGrid>
      <MetricTile label="订单" value={String(orders.length)} detail="均为虚拟回测订单" />
      <MetricTile label="成交" value={String(data.fills.length)} detail="P06 虚拟成交" />
      <MetricTile label="成交率" value={quality ? percent.format(Number(quality.fill_rate)) : "不可用"} detail="P13 非生产评分卡" />
      <MetricTile label="P95 不利滑点" value={quality ? `${quality.p95_adverse_slippage_bps} bps` : "不可用"} detail="样本量明确有限" />
    </MetricGrid>
    {replay ? <Surface kicker="TRADE REPLAY" title="归一化报价包络与时间对齐虚拟成交" aside={<StatusBadge label="非原始交易所 K 线" tone="warning" />}>
      <CandlestickTradeChart
        data={replay.payload.candles.map((candle) => ({
          time: Math.floor(Date.parse(candle.time) / 1000) as UTCTimestamp,
          open: Number(candle.open), high: Number(candle.high), low: Number(candle.low), close: Number(candle.close),
        }))}
        markers={replay.payload.replay_markers.map((marker) => ({
          time: Math.floor(Date.parse(marker.time) / 1000) as UTCTimestamp,
          label: marker.label, price: Number(marker.price), kind: marker.marker_type,
        }))}
      />
      <p className="data-disclaimer">高/低分别是 bid/ask，开/收是 last；这是 P13 归一化报价回放，不冒充逐分钟 OHLC。成交标记来自独立 P13 Paper 工件并按事件时间精确对齐。</p>
    </Surface> : null}
    <Surface kicker="ORDER TRACE" title="订单与七段决策链">
      <div className="table-scroll"><table><thead><tr><th>订单</th><th>标的</th><th>方向</th><th>状态</th><th>成交量</th><th>决策链</th></tr></thead><tbody>
        {orders.map((order) => <tr key={order.entity_id}><td>{order.payload.order_id}</td><td>{order.payload.instrument_id}</td><td>{order.payload.side}</td><td>{order.payload.status}</td><td>{order.payload.filled_quantity}/{order.payload.quantity}</td><td><Link className="trace-link" href={`/execution/orders/${encodeURIComponent(order.entity_id)}`}>查看完整链</Link></td></tr>)}
      </tbody></table></div>
    </Surface>
    <Surface kicker="FILLS" title="成交事实">
      <VirtualDataTable caption="成交事实" columns={[{ key: "fill", label: "成交" }, { key: "order", label: "订单" }, { key: "price", label: "价格" }, { key: "fee", label: "费用" }, { key: "role", label: "流动性角色" }]}
        rows={data.fills.map((fill) => ({ fill: fill.payload.fill_id, order: fill.payload.order_id, price: fill.payload.execution_price, fee: `${fill.payload.fee} ${fill.payload.fee_asset_id}`, role: fill.payload.liquidity_role }))} />
    </Surface>
  </>;
}

function StrategiesView({ data, filters }: Readonly<{ data: WorkbenchResponse; filters: WorkspaceFilters }>) {
  const strategies = data.strategies.filter((item) => filters.strategy === "all" || item.payload.strategy_id === filters.strategy);
  const signals = data.signals.filter((item) => filters.strategy === "all" || item.payload.strategy_id === filters.strategy);
  return <>
    <MetricGrid>
      <MetricTile label="策略记录" value={String(strategies.length)} detail="研究/回测阶段" />
      <MetricTile label="Paper 信号" value={String(signals.length)} detail="order_capability=false" />
      <MetricTile label="生产 Alpha 声明" value="无" detail="由 schema 强制为 false" />
      <MetricTile label="网页参数编辑" value="锁定" detail="只读 VIEWER" />
    </MetricGrid>
    <Surface kicker="STRATEGY CATALOG" title="策略版本">
      <VirtualDataTable caption="策略目录" columns={[{ key: "strategy", label: "策略" }, { key: "version", label: "版本" }, { key: "status", label: "阶段" }, { key: "pnl", label: "净损益" }, { key: "drawdown", label: "最大回撤" }, { key: "model", label: "目录模型关联" }]}
        rows={strategies.map((item) => ({ strategy: item.payload.strategy_id, version: item.payload.version, status: item.payload.status, pnl: `${item.payload.net_pnl} ${item.payload.reporting_asset_id}`, drawdown: item.payload.maximum_drawdown, model: `${item.payload.model_id}（非因果声明）` }))} />
    </Surface>
    <Surface kicker="SIGNALS" title="组合提案信号">
      <VirtualDataTable caption="组合提案信号" columns={[{ key: "signal", label: "信号" }, { key: "instrument", label: "标的" }, { key: "normalized", label: "标准化值" }, { key: "current", label: "当前权重" }, { key: "target", label: "目标权重" }, { key: "impact", label: "估算冲击 bps" }]}
        rows={signals.map((item) => ({ signal: item.payload.signal_id, instrument: item.payload.instrument_id, normalized: item.payload.normalized_signal, current: item.payload.current_weight, target: item.payload.target_weight, impact: item.payload.estimated_impact_bps }))} />
    </Surface>
  </>;
}

function ModelsView({ data }: Readonly<{ data: WorkbenchResponse }>) {
  const selected = data.model_metrics.find((item) => item.payload.selected);
  return <>
    <MetricGrid>
      <MetricTile label="候选模型" value={String(data.model_metrics.length)} detail="同切分、同成本预算" />
      <MetricTile label="规则选择" value={selected?.payload.model_id ?? "未选择"} detail="不等于生产 Champion" />
      <MetricTile label="最终 Holdout" value="关闭" detail="所有记录强制 false" />
      <MetricTile label="模型发布" value="无入口" detail="P15 VIEWER 权限" />
    </MetricGrid>
    <Surface kicker="FAIR MODEL COUNCIL" title="候选模型对照">
      <VirtualDataTable caption="模型候选" columns={[{ key: "model", label: "模型" }, { key: "family", label: "家族" }, { key: "modality", label: "模态" }, { key: "loss", label: "Primary loss" }, { key: "train", label: "训练秒" }, { key: "memory", label: "峰值 MB" }, { key: "selected", label: "选择" }]}
        rows={data.model_metrics.map((item) => ({ model: item.payload.model_id, family: item.payload.family, modality: item.payload.modality, loss: item.payload.metric_value, train: item.payload.train_seconds, memory: item.payload.peak_memory_mb, selected: item.payload.selected ? "规则选择" : "拒绝" }))} />
    </Surface>
    <Surface kicker="MODEL CARDS" title="已登记模型">
      <div className="card-grid">{data.models.map((item) => <article className="compact-card" key={item.entity_id}><StatusBadge label={item.payload.status} tone="neutral" /><h3>{item.payload.model_id}</h3><p>{item.payload.family} · {item.payload.modality}</p><small>{item.payload.metric_name} = {item.payload.metric_value} · observations {item.payload.observations}</small></article>)}</div>
    </Surface>
  </>;
}

function MarketView({ data }: Readonly<{ data: WorkbenchResponse }>) {
  const ohlc = data.market.find((item) => item.payload.bar_semantics === "OHLC");
  const derivatives = data.market.find((item) => item.payload.funding_rate !== null);
  return <>
    <MetricGrid>
      <MetricTile label="市场记录" value={String(data.market.length)} detail="历史/公开夹具分层" />
      <MetricTile label="标记价格" value={derivatives?.payload.mark_price ?? "不可用"} detail={derivatives?.payload.venue_id ?? "无来源"} />
      <MetricTile label="基差" value={derivatives?.payload.basis ?? "不可用"} detail="mark - index" />
      <MetricTile label="资金费率" value={derivatives?.payload.funding_rate ?? "不可用"} detail="公开历史帧" />
    </MetricGrid>
    {ohlc ? <Surface kicker="HISTORICAL OHLC" title="FOMC 事件窗口公开历史 K 线" aside={<StatusBadge label="21 个 1m 点" tone="neutral" />}>
      <CandlestickTradeChart data={ohlc.payload.candles.map((candle) => ({ time: Math.floor(Date.parse(candle.time) / 1000) as UTCTimestamp, open: Number(candle.open), high: Number(candle.high), low: Number(candle.low), close: Number(candle.close) }))} markers={[]} />
      <p className="data-disclaimer">来源 {ohlc.source_artifact}；这是 2024-01-31 的公开历史回放，不是当前行情。</p>
    </Surface> : null}
    <Surface kicker="CROSS VENUE CONTEXT" title="衍生品上下文">
      <dl className="fact-list">
        <div><dt>场所</dt><dd>{derivatives?.payload.venue_id ?? "不可用"}</dd></div>
        <div><dt>Index</dt><dd>{derivatives?.payload.index_price ?? "不可用"}</dd></div>
        <div><dt>Mark</dt><dd>{derivatives?.payload.mark_price ?? "不可用"}</dd></div>
        <div><dt>Open interest</dt><dd>{derivatives?.payload.open_interest ?? "来源未提供"}</dd></div>
        <div><dt>建议</dt><dd>不提供买卖建议</dd></div>
      </dl>
    </Surface>
  </>;
}

function IntelligenceView({ data, filters }: Readonly<{ data: WorkbenchResponse; filters: WorkspaceFilters }>) {
  const replay = data.market.find((item) => item.payload.data_kind === "HISTORICAL_REPLAY");
  return <>
    <MetricGrid>
      <MetricTile label="事件簇" value={String(data.events.length)} detail="影响均显式估算" />
      <MetricTile label="证据" value={String(data.claims.length)} detail="全文权限受限" />
      <MetricTile label="叙事" value={String(data.narratives.length)} detail="独立作者与协调风险" />
      <MetricTile label="来源" value={String(data.sources.length)} detail="按政策处置" />
    </MetricGrid>
    <Surface kicker="EVENT RADAR" title="事件雷达">
      <div className="event-grid">{data.events.map((item) => <article className="event-card" key={item.entity_id}><div><StatusBadge label={item.payload.risk_action} tone={item.payload.risk_action === "HALT" ? "danger" : "warning"} /><span className="quality-badge">{item.payload.status}</span></div><h3>{item.payload.event_cluster_id}</h3><p>{item.payload.affected_assets.join(" · ")} · {item.payload.independent_family_count} 个独立来源家族</p><dl className="impact-strip"><div><dt>5m</dt><dd>{percent.format(Number(item.payload.impact_5m))}</dd></div><div><dt>30m</dt><dd>{percent.format(Number(item.payload.impact_30m))}</dd></div><div><dt>4h</dt><dd>{percent.format(Number(item.payload.impact_4h))}</dd></div><div><dt>1d</dt><dd>{percent.format(Number(item.payload.impact_1d))}</dd></div><div><dt>7d</dt><dd>{percent.format(Number(item.payload.impact_7d))}</dd></div></dl><footer>置信度 {percent.format(Number(item.payload.confidence))} · 非权威估算 · 不直接生成订单</footer></article>)}</div>
    </Surface>
    <section className="dashboard-grid">
      <Surface kicker="EVIDENCE GRAPH" title="证据关系">
        <ol className="evidence-list">{data.claims.map((claim) => <li key={claim.entity_id}><span className={`relation relation-${claim.payload.relation.toLowerCase()}`}>{claim.payload.relation}</span><div><strong>{claim.payload.claim_id}</strong><small>{claim.payload.source_family_id} · {claim.payload.model_version}</small></div><span>{claim.payload.lawful_excerpt_available ? "可显示合法摘录" : "全文受限，仅显示证据 ID"}</span></li>)}</ol>
      </Surface>
      <Surface kicker="ALERT INBOX" title="事件风险告警">
        <div className="alert-list">{data.events.map((item) => <article key={item.entity_id}><StatusBadge label={item.payload.risk_action} tone="warning" /><strong>{item.payload.event_cluster_id}</strong><small>风险动作只进入独立风险层，不绕过限额。</small></article>)}</div>
      </Surface>
    </section>
    {replay ? <Surface kicker="EVENT REPLAY" title={`事件窗口回放 · ${filters.timezone}`}><CandlestickTradeChart data={replay.payload.candles.map((candle) => ({ time: Math.floor(Date.parse(candle.time) / 1000) as UTCTimestamp, open: Number(candle.open), high: Number(candle.high), low: Number(candle.low), close: Number(candle.close) }))} markers={[]} /></Surface> : null}
    <section className="dashboard-grid">
      <Surface kicker="NARRATIVE MONITOR" title="叙事传播"><div className="narrative-list">{data.narratives.map((item) => <article key={item.entity_id}><strong>{item.payload.topic}</strong><span>{item.payload.propagation_stage}</span><small>{item.payload.independent_author_count} 位独立作者 · 协调风险 {percent.format(Number(item.payload.coordination_risk))}</small></article>)}</div></Surface>
      <Surface kicker="SOURCE MONITOR" title="来源政策"><div className="source-list">{data.sources.map((item) => <article key={item.entity_id}><div><strong>{item.payload.source_id}</strong><span className="quality-badge">{item.payload.policy_status}</span></div><p>{item.payload.runtime_state} · {item.payload.disposition}</p><small>{item.payload.reason_codes.join(" · ")}</small></article>)}</div></Surface>
    </section>
  </>;
}

function RiskView({ data }: Readonly<{ data: WorkbenchResponse }>) {
  const risk = data.risk.payload;
  return <>
    <RiskStateBanner state={risk.state} reasons={[...risk.reason_codes]} />
    <MetricGrid>
      <MetricTile label="回撤" value={percent.format(Number(risk.drawdown_fraction))} detail="服务端风险快照" />
      <MetricTile label="总权重" value={percent.format(Number(risk.gross_weight))} detail="开发组合" />
      <MetricTile label="保证金利用率" value={percent.format(Number(risk.margin_utilization))} detail="签名策略比较" />
      <MetricTile label="流动性分数" value={decimal.format(Number(risk.liquidity_score))} detail="最低值限额" />
    </MetricGrid>
    <Surface kicker="LIMITS & HEADROOM" title="签名策略限额（不可编辑）">
      <VirtualDataTable caption="风险限额" columns={[{ key: "metric", label: "指标" }, { key: "current", label: "当前" }, { key: "limit", label: "限额" }, { key: "headroom", label: "余量" }, { key: "state", label: "状态" }]}
        rows={data.risk_limits.map((item) => ({ metric: item.payload.metric, current: item.payload.current_value, limit: item.payload.limit_value, headroom: item.payload.headroom, state: item.payload.breached ? "BREACHED" : "WITHIN" }))} />
    </Surface>
    <Surface kicker="CIRCUIT BREAKERS" title="风险与事故联动">
      <div className="card-grid">{data.incidents.map((item) => <article className="compact-card" key={item.entity_id}><StatusBadge label={item.payload.severity} tone="danger" /><h3>{item.payload.fault_kind}</h3><p>{item.payload.risk_state} · new risk blocked</p><small>{item.payload.reason_code}</small></article>)}</div>
    </Surface>
  </>;
}

function ResearchView({ data }: Readonly<{ data: WorkbenchResponse }>) {
  const failures = data.research_runs.filter((item) => item.payload.status !== "SUCCEEDED");
  return <>
    <MetricGrid>
      <MetricTile label="研究运行" value={String(data.research_runs.length)} detail="哈希链账本" />
      <MetricTile label="负结果" value={String(failures.length)} detail="失败与错误完整保留" />
      <MetricTile label="模型候选" value={String(data.model_metrics.length)} detail="公平比较" />
      <MetricTile label="最终 Holdout" value="未打开" detail="所有记录 false" />
    </MetricGrid>
    <Surface kicker="EXPERIMENT LEDGER" title="研究运行">
      <VirtualDataTable caption="研究运行" columns={[{ key: "run", label: "Run" }, { key: "model", label: "模型" }, { key: "status", label: "状态" }, { key: "decision", label: "推广决定" }, { key: "metric", label: "指标" }, { key: "reason", label: "失败原因" }]}
        rows={data.research_runs.map((item) => ({ run: item.payload.run_id, model: item.payload.model_id, status: item.payload.status, decision: item.payload.promotion_decision, metric: item.payload.metrics.map((metric) => `${metric.name}=${metric.value}`).join(" · ") || "—", reason: item.payload.failure_reason ?? "—" }))} />
    </Surface>
    <Surface kicker="REPRODUCIBILITY" title="可复现血缘">
      <div className="hash-list">{data.research_runs.map((item) => <article key={item.entity_id}><strong>{item.payload.run_id}</strong><code>dataset {item.payload.dataset_sha256}</code><code>split {item.payload.split_sha256}</code><small>commit {item.payload.code_commit}</small></article>)}</div>
    </Surface>
  </>;
}

function ResearchIntelligenceView({ data }: Readonly<{ data: WorkbenchResponse }>) {
  return <>
    <MetricGrid>
      <MetricTile label="来源策略" value={String(data.sources.length)} detail="默认拒绝/显式处置" />
      <MetricTile label="证据边" value={String(data.claims.length)} detail="支持与反驳并存" />
      <MetricTile label="可复现运行" value={String(data.research_runs.length)} detail="失败不删除" />
      <MetricTile label="订单能力" value="无" detail="外部知识不能下单" />
    </MetricGrid>
    <Surface kicker="SOURCE RIGHTS" title="来源许可与运行状态"><DataQualityGrid items={data.sources.map((item) => ({ id: item.entity_id, label: item.payload.source_id, state: item.payload.runtime_state === "READY" ? "READY" : "DEGRADED", reason: `${item.payload.disposition} · ${item.payload.reason_codes.join(" · ")}` }))} /></Surface>
    <section className="dashboard-grid">
      <Surface kicker="EVIDENCE" title="证据关系"><ol className="evidence-list">{data.claims.map((item) => <li key={item.entity_id}><span className={`relation relation-${item.payload.relation.toLowerCase()}`}>{item.payload.relation}</span><div><strong>{item.payload.claim_id}</strong><small>{item.payload.policy_id}</small></div><span>安全渲染：{item.payload.lawful_excerpt_available ? "允许摘录" : "仅标识符"}</span></li>)}</ol></Surface>
      <Surface kicker="FAILURE RETENTION" title="负结果保留"><div className="alert-list">{data.research_runs.filter((item) => item.payload.status !== "SUCCEEDED").map((item) => <article key={item.entity_id}><StatusBadge label={item.payload.status} tone="warning" /><strong>{item.payload.run_id}</strong><small>{item.payload.failure_reason}</small></article>)}</div></Surface>
    </section>
  </>;
}

function DataView({ data }: Readonly<{ data: WorkbenchResponse }>) {
  const recordCount = 5
    + data.positions.length + data.risk_limits.length + data.strategies.length
    + data.models.length + data.model_metrics.length + data.signals.length
    + data.orders.length + data.fills.length + data.execution_quality.length
    + data.market.length + data.events.length + data.claims.length
    + data.narratives.length + data.sources.length + data.data_health.length
    + data.research_runs.length + data.incidents.length + data.system_health.length
    + data.order_traces.length;
  return <>
    <MetricGrid>
      <MetricTile label="Provider 状态" value={String(data.data_health.length)} detail="P10 来源监控" />
      <MetricTile label="缺口总数" value={String(data.data_health.reduce((sum, item) => sum + item.payload.gap_count, 0))} detail="不隐藏缺失" />
      <MetricTile label="快照记录" value={String(recordCount)} detail="同一内容哈希" />
      <MetricTile label="浏览器直连数据库" value="禁止" detail="仅 loopback Read API" />
    </MetricGrid>
    <Surface kicker="PROVIDER REGISTRY" title="来源健康"><DataQualityGrid items={data.data_health.map((item) => ({ id: item.entity_id, label: item.payload.provider_id, state: item.payload.state, reason: `${item.payload.policy_status} · ${item.payload.reason_codes.join(" · ")}` }))} /></Surface>
    <Surface kicker="LINEAGE" title="内容寻址血缘">
      <VirtualDataTable caption="来源工件" columns={[{ key: "projection", label: "投影" }, { key: "entity", label: "实体" }, { key: "source", label: "来源" }, { key: "sha", label: "SHA-256" }, { key: "quality", label: "质量" }]}
        rows={[data.account, data.pnl_attribution, ...data.data_health, ...data.market].map((item) => ({ projection: item.projection, entity: item.entity_id, source: item.source_artifact, sha: item.source_sha256, quality: item.quality_state }))} />
    </Surface>
  </>;
}

function IncidentsView({ data, filters }: Readonly<{ data: WorkbenchResponse; filters: WorkspaceFilters }>) {
  return <>
    <MetricGrid>
      <MetricTile label="事故演练" value={String(data.incidents.length)} detail="全部 P13 非资金演练" />
      <MetricTile label="SEV0" value={String(data.incidents.filter((item) => item.payload.severity === "SEV0").length)} detail="数据库/进程" />
      <MetricTile label="已恢复" value={String(data.incidents.filter((item) => item.payload.status === "RECOVERED").length)} detail="有恢复证据" />
      <MetricTile label="真实资金影响" value="0" detail="schema 强制 false" />
    </MetricGrid>
    <div className="incident-grid">{data.incidents.map((item) => <Surface key={item.entity_id} kicker={`${item.payload.severity} · ${item.payload.fault_kind}`} title={item.payload.incident_id} aside={<StatusBadge label={item.payload.status} tone="positive" />}>
      <IncidentTimeline items={item.payload.timeline.map((point) => ({ id: `${item.entity_id}:${point.sequence}`, time: point.occurred_at, title: point.event_type, detail: `${point.state} · ${point.evidence_ids.join(" · ")}`, tone: point.operator_action_required ? "warning" : "positive" }))} />
      <p className="data-disclaimer">Runbook {item.payload.runbook_path} · 对账 {item.payload.reconciliation_clear ? "通过" : "未通过"} · 时区 {filters.timezone}</p>
    </Surface>)}</div>
  </>;
}

function SystemView({ data, filters }: Readonly<{ data: WorkbenchResponse; filters: WorkspaceFilters }>) {
  return <>
    <MetricGrid>
      <MetricTile label="历史健康检查" value={String(data.system_health.length)} detail="非实时探针" />
      <MetricTile label="就绪" value={String(data.system_health.filter((item) => item.payload.status === "READY").length)} detail="P14 CI 证据" />
      <MetricTile label="对账" value={data.reconciliation.payload.state} detail="P12 快照" />
      <MetricTile label="Live Trading" value="LOCKED" detail="不可从网页解除" />
    </MetricGrid>
    <Surface kicker="SERVICE HEALTH" title="历史契约检查"><div className="card-grid">{data.system_health.map((item) => <article className="compact-card" key={item.entity_id}><StatusBadge label={item.payload.status} tone={item.payload.status === "READY" ? "positive" : "danger"} /><h3>{item.payload.service_id}</h3><p>{item.payload.check_name} · {item.payload.version}</p><small>{item.payload.detail}</small><small>{formatTime(item.payload.checked_at, filters.timezone)}</small></article>)}</div></Surface>
    <Surface kicker="RECONCILIATION" title="资金事实恢复边界"><SignalDecisionTrace steps={[
      { id: "snapshot", label: "账户快照", outcome: data.reconciliation.payload.venue_id },
      { id: "sequence", label: "序列", outcome: String(data.reconciliation.payload.last_sequence) },
      { id: "unknown", label: "未知资金事实", outcome: String(data.reconciliation.payload.unknown_local_fill_count + data.reconciliation.payload.unknown_local_order_count + data.reconciliation.payload.unknown_venue_fill_count + data.reconciliation.payload.unknown_venue_order_count) },
      { id: "state", label: "结果", outcome: data.reconciliation.payload.state },
    ]} /></Surface>
    <Surface kicker="SNAPSHOT" title="工作台内容哈希"><div className="snapshot-hash"><code>{data.snapshot_sha256}</code><p>所有页面在本次请求中消费同一不可变快照；P16 的 Prometheus/Grafana 尚未开始。</p></div></Surface>
  </>;
}

function pageContent(page: WorkspacePageKey, data: WorkbenchResponse, filters: WorkspaceFilters) {
  switch (page) {
    case "overview": return <OverviewView data={data} filters={filters} />;
    case "live": return <LiveView data={data} filters={filters} />;
    case "performance": return <PerformanceView data={data} filters={filters} />;
    case "execution": return <ExecutionView data={data} filters={filters} />;
    case "strategies": return <StrategiesView data={data} filters={filters} />;
    case "models": return <ModelsView data={data} />;
    case "market": return <MarketView data={data} />;
    case "intelligence": return <IntelligenceView data={data} filters={filters} />;
    case "risk": return <RiskView data={data} />;
    case "research": return <ResearchView data={data} />;
    case "research-intelligence": return <ResearchIntelligenceView data={data} />;
    case "data": return <DataView data={data} />;
    case "incidents": return <IncidentsView data={data} filters={filters} />;
    case "system": return <SystemView data={data} filters={filters} />;
  }
}

export function WorkspacePage({
  page,
  data,
  filters,
}: Readonly<{ page: WorkspacePageKey; data: WorkbenchResponse; filters: WorkspaceFilters }>) {
  const definition = pages[page];
  return (
    <DataState
      state="STALE"
      asOf={data.account.as_of_time}
      source={data.account.source_artifact}
      authoritative={data.account.authoritative}
      estimated={data.events.some((item) => item.estimated)}
      lastSuccessAt={data.account.projected_at}
      reason="这是经哈希验证的历史开发/Paper/fixture 快照，不是实时账户流。"
    >
      <div className="page-stack">
        <header className="page-header">
          <div><p className="eyebrow">{definition.eyebrow}</p><h1>{definition.title}</h1><p className="lede">{definition.description}</p></div>
          <div className="freshness" title={data.snapshot_sha256}>
            <span>数据截至 · {filters.timezone}</span>
            <strong>{formatTime(data.account.as_of_time, filters.timezone)}</strong>
            <small>{filters.account} · {filters.currency} · 快照 {data.snapshot_sha256.slice(0, 12)}… · {filters.range}</small>
          </div>
        </header>
        {pageContent(page, data, filters)}
      </div>
    </DataState>
  );
}
