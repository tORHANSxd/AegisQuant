import type { ReactNode } from "react";

export type DataStateKind =
  | "LOADING"
  | "EMPTY"
  | "LIVE"
  | "STALE"
  | "DEGRADED"
  | "DISCONNECTED"
  | "ERROR"
  | "PERMISSION_DENIED";

const labels: Record<DataStateKind, string> = {
  LOADING: "加载中",
  EMPTY: "暂无数据",
  LIVE: "已连接",
  STALE: "数据陈旧",
  DEGRADED: "降级运行",
  DISCONNECTED: "连接中断",
  ERROR: "读取失败",
  PERMISSION_DENIED: "无权查看",
};

export interface DataStateProps {
  state: DataStateKind;
  asOf?: string;
  latencyMs?: number;
  source?: string;
  authoritative?: boolean;
  estimated?: boolean;
  lastSuccessAt?: string;
  reason?: string;
  children?: ReactNode;
}

export function DataState({
  state,
  asOf,
  latencyMs,
  source,
  authoritative = false,
  estimated = false,
  lastSuccessAt,
  reason,
  children,
}: Readonly<DataStateProps>) {
  if (state === "LOADING") {
    return (
      <section className="data-state state-loading" aria-live="polite" aria-busy="true">
        <span className="loading-line" />
        <span className="loading-line short" />
        <p>{labels[state]}：正在读取服务端快照。</p>
      </section>
    );
  }
  if (state === "EMPTY") {
    return <EmptyState title={labels[state]} detail={reason ?? "当前筛选条件没有记录。"} />;
  }
  if (state === "ERROR" || state === "PERMISSION_DENIED") {
    return (
      <ErrorBoundaryPanel
        title={labels[state]}
        detail={reason ?? "请求已安全终止，没有使用旧数据冒充当前状态。"}
      />
    );
  }
  return (
    <section className={`data-state state-${state.toLowerCase()}`} aria-live="polite">
      {state !== "LIVE" ? (
        <div className="state-warning" role="status">
          <strong>{labels[state]}</strong>
          <span>{reason ?? "界面已明确保留最后一次成功快照，不将其标记为实时。"}</span>
        </div>
      ) : null}
      {children}
      <footer className="data-provenance" aria-label="数据来源与新鲜度">
        <span>状态 {labels[state]}</span>
        <span>截至 {asOf ?? "未知"}</span>
        <span>延迟 {latencyMs === undefined ? "未知" : `${latencyMs} ms`}</span>
        <span>来源 {source ?? "未声明"}</span>
        <span>{authoritative ? "权威口径" : "非权威口径"}</span>
        <span>{estimated ? "含估算" : "非估算"}</span>
        <span>最近成功 {lastSuccessAt ?? "未知"}</span>
      </footer>
    </section>
  );
}

export function EmptyState({ title, detail }: Readonly<{ title: string; detail: string }>) {
  return (
    <section className="empty-state" role="status">
      <span aria-hidden="true">○</span>
      <h3>{title}</h3>
      <p>{detail}</p>
    </section>
  );
}

export function ErrorBoundaryPanel({
  title,
  detail,
}: Readonly<{ title: string; detail: string }>) {
  return (
    <section className="error-panel" role="alert">
      <span aria-hidden="true">!</span>
      <div>
        <h3>{title}</h3>
        <p>{detail}</p>
      </div>
    </section>
  );
}
