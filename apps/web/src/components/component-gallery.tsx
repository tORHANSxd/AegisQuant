"use client";

import type { Time } from "lightweight-charts";

import {
  CommandPalette,
  DataQualityGrid,
  EnvironmentBadge,
  ExportMenu,
  FilterBar,
  FreshnessIndicator,
  IncidentTimeline,
  MetricDelta,
  MetricTile,
  OrderTimeline,
  RiskStateBanner,
  SignalDecisionTrace,
  StatusBadge,
  VirtualDataTable,
} from "./common";
import { DataState, EmptyState, ErrorBoundaryPanel, type DataStateKind } from "./data-state";
import {
  AttributionWaterfall,
  CandlestickTradeChart,
  CorrelationMatrix,
  DrawdownChart,
  EquityChart,
  ExposureTreemap,
  ModelCalibrationChart,
  PnLHeatmap,
} from "./charts/chart-suite";

const now = "2026-09-01T21:50:00Z";
const points = [
  { label: "09:00", value: 10000 },
  { label: "10:00", value: 9992 },
  { label: "11:00", value: 10018 },
  { label: "12:00", value: 10011 },
];
const timeline = [
  { id: "one", time: now, title: "信号形成", detail: "历史开发夹具", tone: "neutral" as const },
  { id: "two", time: now, title: "风险审查", detail: "NORMAL", tone: "positive" as const },
];
const candles = [
  { time: "2026-08-29" as Time, open: 100, high: 108, low: 96, close: 104 },
  { time: "2026-08-30" as Time, open: 104, high: 110, low: 101, close: 102 },
  { time: "2026-08-31" as Time, open: 102, high: 113, low: 100, close: 111 },
];

function GalleryItem({ title, children }: Readonly<{ title: string; children: React.ReactNode }>) {
  return <section className="gallery-item"><h2>{title}</h2>{children}</section>;
}

export function ComponentGallery({ state = "LIVE" }: Readonly<{ state?: DataStateKind }>) {
  return (
    <main className={`component-gallery gallery-${state.toLowerCase()}`}>
      <h1>AegisQuant 通用组件状态画廊</h1>
      <DataState state={state} asOf={now} latencyMs={42} source="P14 verified fixture" authoritative estimated={false} lastSuccessAt={now} reason="Storybook 状态演示。">
        <p>此容器展示当前数据状态及完整来源元数据。</p>
      </DataState>
      <div className="gallery-grid">
        <GalleryItem title="MetricTile"><MetricTile label="账户权益" value="10,011.00" unit="USDT" detail="权威口径" /></GalleryItem>
        <GalleryItem title="MetricDelta"><MetricDelta value="+0.18%" direction="up" /></GalleryItem>
        <GalleryItem title="StatusBadge"><StatusBadge label="STALE" tone="warning" /></GalleryItem>
        <GalleryItem title="FreshnessIndicator"><FreshnessIndicator asOf={now} state="STALE" /></GalleryItem>
        <GalleryItem title="RiskStateBanner"><RiskStateBanner state="CAUTION" reasons={["历史快照", "禁止实盘"]} /></GalleryItem>
        <GalleryItem title="EnvironmentBadge"><EnvironmentBadge environment="RESEARCH" locked /></GalleryItem>
        <GalleryItem title="EquityChart"><EquityChart points={points} /></GalleryItem>
        <GalleryItem title="DrawdownChart"><DrawdownChart points={points.map((point, index) => ({ ...point, value: -index / 100 }))} /></GalleryItem>
        <GalleryItem title="CandlestickTradeChart"><CandlestickTradeChart data={candles} /></GalleryItem>
        <GalleryItem title="AttributionWaterfall"><AttributionWaterfall points={[{ label: "策略", value: 12 }, { label: "费用", value: -2 }]} /></GalleryItem>
        <GalleryItem title="PnLHeatmap"><PnLHeatmap points={[{ label: "周一", value: 2 }, { label: "周二", value: -1 }]} /></GalleryItem>
        <GalleryItem title="ExposureTreemap"><ExposureTreemap points={[{ label: "BTC", value: 60 }, { label: "ETH", value: 40 }]} /></GalleryItem>
        <GalleryItem title="CorrelationMatrix"><CorrelationMatrix points={[{ label: "BTC", value: 1 }, { label: "ETH", value: 0.7 }]} /></GalleryItem>
        <GalleryItem title="OrderTimeline"><OrderTimeline items={timeline} /></GalleryItem>
        <GalleryItem title="SignalDecisionTrace"><SignalDecisionTrace steps={[{ id: "signal", label: "信号", outcome: "ABSTAIN" }, { id: "risk", label: "风控", outcome: "CAUTION" }]} /></GalleryItem>
        <GalleryItem title="DataQualityGrid"><DataQualityGrid items={[{ id: "market", label: "市场数据", state: "STALE", reason: "历史夹具" }]} /></GalleryItem>
        <GalleryItem title="ModelCalibrationChart"><ModelCalibrationChart points={[{ label: "0.2", value: 0.18 }, { label: "0.8", value: 0.74 }]} /></GalleryItem>
        <GalleryItem title="IncidentTimeline"><IncidentTimeline items={timeline} /></GalleryItem>
        <GalleryItem title="VirtualDataTable"><VirtualDataTable caption="订单" columns={[{ key: "id", label: "订单" }, { key: "status", label: "状态" }]} rows={[{ id: "order-1", status: "FILLED" }]} /></GalleryItem>
        <GalleryItem title="FilterBar"><FilterBar><label>状态<select defaultValue="all"><option value="all">全部</option><option value="stale">陈旧</option></select></label><button type="button">应用</button></FilterBar></GalleryItem>
        <GalleryItem title="CommandPalette"><CommandPalette commands={["打开总览", "打开事件情报"]} /></GalleryItem>
        <GalleryItem title="EmptyState"><EmptyState title="暂无事件" detail="当前过滤条件没有证据事件。" /></GalleryItem>
        <GalleryItem title="ErrorBoundaryPanel"><ErrorBoundaryPanel title="读取失败" detail="旧数据不会冒充实时数据。" /></GalleryItem>
        <GalleryItem title="ExportMenu"><ExportMenu formats={["CSV", "JSON"]} /></GalleryItem>
      </div>
    </main>
  );
}
