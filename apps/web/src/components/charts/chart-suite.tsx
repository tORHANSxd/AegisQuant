"use client";

import type { EChartsOption } from "echarts";
import type { CandlestickData, SeriesMarker, Time } from "lightweight-charts";
import { useEffect, useRef } from "react";

interface SeriesPoint {
  label: string;
  value: number;
}

function ChartTable({ title, points }: Readonly<{ title: string; points: SeriesPoint[] }>) {
  return (
    <details className="chart-data">
      <summary>{title}数据表</summary>
      <table>
        <thead><tr><th>时间/类别</th><th>值</th></tr></thead>
        <tbody>{points.map((point) => <tr key={point.label}><td>{point.label}</td><td>{point.value}</td></tr>)}</tbody>
      </table>
    </details>
  );
}

function EChartSurface({
  title,
  summary,
  points,
  option,
}: Readonly<{ title: string; summary: string; points: SeriesPoint[]; option: EChartsOption }>) {
  const container = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = container.current;
    if (!node) return;
    let disposed = false;
    let cleanup: () => void = () => undefined;
    void import("echarts").then((echarts) => {
      if (disposed) return;
      const chart = echarts.init(node, undefined, { renderer: "canvas" });
      chart.setOption(option);
      const observer = new ResizeObserver(() => chart.resize());
      observer.observe(node);
      cleanup = () => {
        observer.disconnect();
        chart.dispose();
      };
    });
    return () => {
      disposed = true;
      cleanup();
    };
  }, [option]);
  return (
    <figure className="chart-surface" aria-label={title}>
      <figcaption><strong>{title}</strong><span>{summary}</span></figcaption>
      <div ref={container} className="chart-canvas" role="img" aria-label={summary} />
      <ChartTable title={title} points={points} />
    </figure>
  );
}

function lineOption(points: SeriesPoint[], area = false): EChartsOption {
  return {
    animation: false,
    grid: { left: 48, right: 18, top: 24, bottom: 32 },
    xAxis: { type: "category", data: points.map((item) => item.label), axisLabel: { color: "#91a8ae" } },
    yAxis: { type: "value", scale: true, axisLabel: { color: "#91a8ae" }, splitLine: { lineStyle: { color: "#213641" } } },
    series: [{ type: "line", data: points.map((item) => item.value), symbol: "none", lineStyle: { color: "#4ed2c5", width: 2 }, areaStyle: area ? { color: "rgba(78,210,197,.16)" } : undefined }],
  };
}

export function EquityChart({ points }: Readonly<{ points: SeriesPoint[] }>) {
  return <EChartSurface title="权益曲线" summary={`共 ${points.length} 个服务端权益点。`} points={points} option={lineOption(points, true)} />;
}

export function DrawdownChart({ points }: Readonly<{ points: SeriesPoint[] }>) {
  const option = lineOption(points, true);
  return <EChartSurface title="回撤曲线" summary="数值越低表示回撤越深。" points={points} option={option} />;
}

function barOption(points: SeriesPoint[]): EChartsOption {
  return {
    animation: false,
    grid: { left: 48, right: 18, top: 24, bottom: 38 },
    xAxis: { type: "category", data: points.map((item) => item.label), axisLabel: { color: "#91a8ae" } },
    yAxis: { type: "value", axisLabel: { color: "#91a8ae" }, splitLine: { lineStyle: { color: "#213641" } } },
    series: [{ type: "bar", data: points.map((item) => ({ value: item.value, itemStyle: { color: item.value >= 0 ? "#5ad29c" : "#ff7768" } })) }],
  };
}

export function AttributionWaterfall({ points }: Readonly<{ points: SeriesPoint[] }>) {
  return <EChartSurface title="归因瀑布" summary="正负贡献由服务端口径分解。" points={points} option={barOption(points)} />;
}

export function PnLHeatmap({ points }: Readonly<{ points: SeriesPoint[] }>) {
  const option: EChartsOption = {
    animation: false,
    grid: { left: 70, right: 18, top: 18, bottom: 32 },
    xAxis: { type: "category", data: points.map((item) => item.label), axisLabel: { color: "#91a8ae" } },
    yAxis: { type: "category", data: ["PnL"], axisLabel: { color: "#91a8ae" } },
    visualMap: { show: false, min: Math.min(...points.map((item) => item.value)), max: Math.max(...points.map((item) => item.value)), inRange: { color: ["#ff7768", "#172831", "#5ad29c"] } },
    series: [{ type: "heatmap", data: points.map((item, index) => [index, 0, item.value]) }],
  };
  return <EChartSurface title="PnL 热力图" summary="颜色与数值同时编码损益。" points={points} option={option} />;
}

export function ExposureTreemap({ points }: Readonly<{ points: SeriesPoint[] }>) {
  const option: EChartsOption = { animation: false, series: [{ type: "treemap", roam: false, label: { color: "#eef6f7" }, data: points.map((item) => ({ name: item.label, value: Math.abs(item.value) })) }] };
  return <EChartSurface title="暴露树图" summary="面积表示绝对暴露，不表达买卖建议。" points={points} option={option} />;
}

export function CorrelationMatrix({ points }: Readonly<{ points: SeriesPoint[] }>) {
  const option: EChartsOption = { animation: false, grid: { left: 60, right: 20, top: 20, bottom: 36 }, xAxis: { type: "category", data: points.map((item) => item.label), axisLabel: { color: "#91a8ae" } }, yAxis: { type: "category", data: ["组合"], axisLabel: { color: "#91a8ae" } }, visualMap: { show: false, min: -1, max: 1, inRange: { color: ["#ff7768", "#172831", "#4ed2c5"] } }, series: [{ type: "heatmap", data: points.map((item, index) => [index, 0, item.value]) }] };
  return <EChartSurface title="相关矩阵" summary="相关系数范围 -1 到 1。" points={points} option={option} />;
}

export function ModelCalibrationChart({ points }: Readonly<{ points: SeriesPoint[] }>) {
  return <EChartSurface title="模型校准" summary="预测概率与观察频率的只读对照。" points={points} option={lineOption(points)} />;
}

export function CandlestickTradeChart({
  data,
  markers = [],
}: Readonly<{
  data: Array<CandlestickData<Time>>;
  markers?: Array<{ time: Time; label: string; price: number; kind: string }>;
}>) {
  const container = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = container.current;
    if (!node) return;
    let disposed = false;
    let cleanup: () => void = () => undefined;
    void import("lightweight-charts").then(({ CandlestickSeries, createChart, createSeriesMarkers }) => {
      if (disposed) return;
      const chart = createChart(node, { autoSize: true, layout: { background: { color: "transparent" }, textColor: "#91a8ae" }, grid: { vertLines: { color: "#213641" }, horzLines: { color: "#213641" } } });
      const series = chart.addSeries(CandlestickSeries, { upColor: "#5ad29c", downColor: "#ff7768", borderVisible: false, wickUpColor: "#5ad29c", wickDownColor: "#ff7768" });
      series.setData(data);
      const renderedMarkers: Array<SeriesMarker<Time>> = markers.map((marker) => ({
        time: marker.time,
        position: "atPriceTop",
        shape: marker.kind === "FILL" ? "arrowUp" : "circle",
        color: marker.kind === "FILL" ? "#f4bd62" : "#4ed2c5",
        price: marker.price,
        text: marker.label,
      }));
      createSeriesMarkers(series, renderedMarkers);
      chart.timeScale().fitContent();
      cleanup = () => chart.remove();
    });
    return () => {
      disposed = true;
      cleanup();
    };
  }, [data, markers]);
  const points = data.map((item) => ({ label: String(item.time), value: item.close }));
  return (
    <figure className="chart-surface" aria-label="K 线与交易">
      <figcaption><strong>K 线与交易</strong><span>价格图仅用于上下文，不构成买卖建议。</span></figcaption>
      <div ref={container} className="chart-canvas" role="img" aria-label="历史 K 线" />
      {markers.length ? <ol className="chart-markers" aria-label="回放标记">{markers.map((marker) => <li key={`${String(marker.time)}:${marker.label}`}><time>{String(marker.time)}</time><strong>{marker.kind}</strong><span>{marker.label} · {marker.price}</span></li>)}</ol> : null}
      <ChartTable title="K 线收盘价" points={points} />
    </figure>
  );
}
