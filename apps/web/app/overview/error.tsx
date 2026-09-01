"use client";

import { ErrorBoundaryPanel } from "../../src/components/data-state";

export default function OverviewError({ reset }: Readonly<{ reset: () => void }>) {
  return (
    <div className="page-stack">
      <ErrorBoundaryPanel
        title="总览读取失败"
        detail="只读 API 当前不可用；系统没有把旧快照伪装成实时数据。"
      />
      <button className="secondary-button" type="button" onClick={reset}>
        重试只读请求
      </button>
    </div>
  );
}
