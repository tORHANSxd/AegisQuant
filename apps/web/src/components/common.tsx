"use client";

import type { ReactNode } from "react";

import { EmptyState, ErrorBoundaryPanel } from "./data-state";

export { EmptyState, ErrorBoundaryPanel };

export function MetricTile({
  label,
  value,
  unit,
  detail,
}: Readonly<{ label: string; value: string; unit?: string; detail?: string }>) {
  return (
    <article className="metric-card">
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{unit ? `${unit} · ` : ""}{detail}</small>
    </article>
  );
}

export function MetricDelta({
  value,
  direction,
}: Readonly<{ value: string; direction: "up" | "down" | "flat" }>) {
  return (
    <span className={`metric-delta ${direction}`} aria-label={`变化 ${value}`}>
      <span aria-hidden="true">{direction === "up" ? "↗" : direction === "down" ? "↘" : "→"}</span>
      {value}
    </span>
  );
}

export function StatusBadge({
  label,
  tone = "neutral",
}: Readonly<{ label: string; tone?: "positive" | "warning" | "danger" | "neutral" }>) {
  return <span className={`status-badge tone-${tone}`}>{label}</span>;
}

export function FreshnessIndicator({
  asOf,
  state,
}: Readonly<{ asOf: string; state: "LIVE" | "STALE" | "DEGRADED" | "DISCONNECTED" }>) {
  return (
    <span className={`freshness-indicator freshness-${state.toLowerCase()}`}>
      <span className="freshness-dot" aria-hidden="true" />
      {state} · <time dateTime={asOf}>{new Date(asOf).toLocaleString("zh-CN")}</time>
    </span>
  );
}

export function RiskStateBanner({
  state,
  reasons,
}: Readonly<{ state: "NORMAL" | "CAUTION" | "REDUCE_ONLY" | "HALTED"; reasons: string[] }>) {
  return (
    <section className={`risk-banner risk-${state.toLowerCase()}`} role="status">
      <strong>风险状态 {state}</strong>
      <span>{reasons.join(" · ")}</span>
    </section>
  );
}

export function EnvironmentBadge({
  environment,
  locked,
}: Readonly<{ environment: "RESEARCH" | "PAPER" | "SHADOW"; locked: true }>) {
  return (
    <span className="environment-badge">
      {environment} · {locked ? "LIVE LOCKED" : ""}
    </span>
  );
}

export interface TimelineItem {
  id: string;
  time: string;
  title: string;
  detail: string;
  tone?: "positive" | "warning" | "danger" | "neutral";
}

function Timeline({ items, label }: Readonly<{ items: TimelineItem[]; label: string }>) {
  return (
    <ol className="timeline" aria-label={label}>
      {items.map((item) => (
        <li key={item.id} className={`tone-${item.tone ?? "neutral"}`}>
          <time dateTime={item.time}>{new Date(item.time).toLocaleTimeString("zh-CN")}</time>
          <strong>{item.title}</strong>
          <span>{item.detail}</span>
        </li>
      ))}
    </ol>
  );
}

export function OrderTimeline({ items }: Readonly<{ items: TimelineItem[] }>) {
  return <Timeline items={items} label="订单时间轴" />;
}

export function IncidentTimeline({ items }: Readonly<{ items: TimelineItem[] }>) {
  return <Timeline items={items} label="事故时间轴" />;
}

export function SignalDecisionTrace({
  steps,
}: Readonly<{ steps: Array<{ id: string; label: string; outcome: string }> }>) {
  return (
    <ol className="decision-trace" aria-label="信号决策链">
      {steps.map((step, index) => (
        <li key={step.id}>
          <span>{index + 1}</span>
          <strong>{step.label}</strong>
          <small>{step.outcome}</small>
        </li>
      ))}
    </ol>
  );
}

export function DataQualityGrid({
  items,
}: Readonly<{ items: Array<{ id: string; label: string; state: string; reason: string }> }>) {
  return (
    <div className="quality-grid" role="list" aria-label="数据质量">
      {items.map((item) => (
        <article role="listitem" key={item.id}>
          <StatusBadge
            label={item.state}
            tone={item.state === "READY" ? "positive" : "warning"}
          />
          <strong>{item.label}</strong>
          <small>{item.reason}</small>
        </article>
      ))}
    </div>
  );
}

export function VirtualDataTable({
  caption,
  columns,
  rows,
  windowStart = 0,
  windowSize = 50,
}: Readonly<{
  caption: string;
  columns: Array<{ key: string; label: string }>;
  rows: Array<Record<string, string>>;
  windowStart?: number;
  windowSize?: number;
}>) {
  const visible = rows.slice(windowStart, windowStart + windowSize);
  return (
    <div className="virtual-table" role="region" aria-label={caption} tabIndex={0}>
      <table aria-rowcount={rows.length}>
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>{columns.map((column) => <th key={column.key}>{column.label}</th>)}</tr>
        </thead>
        <tbody>
          {visible.map((row, rowIndex) => (
            <tr key={`${windowStart + rowIndex}:${columns.map((item) => row[item.key]).join(":")}`}>
              {columns.map((column) => <td key={column.key}>{row[column.key] ?? "—"}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function FilterBar({
  children,
  label = "筛选条件",
}: Readonly<{ children: ReactNode; label?: string }>) {
  return <form className="filter-bar" aria-label={label}>{children}</form>;
}

export function CommandPalette({ commands }: Readonly<{ commands: string[] }>) {
  return (
    <section className="command-palette" aria-label="只读命令面板">
      <label htmlFor="command-search">查找页面或只读操作</label>
      <input id="command-search" type="search" placeholder="输入关键词…" />
      <ul>{commands.map((command) => <li key={command}>{command}</li>)}</ul>
    </section>
  );
}

export function ExportMenu({ formats }: Readonly<{ formats: string[] }>) {
  return (
    <details className="export-menu">
      <summary>导出当前只读视图</summary>
      <ul>{formats.map((format) => <li key={format}><button type="button">{format}</button></li>)}</ul>
    </details>
  );
}
