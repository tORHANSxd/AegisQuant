"use client";

import { ErrorBoundaryPanel } from "../../src/components/data-state";

export default function IntelligenceError({ reset }: Readonly<{ reset: () => void }>) {
  return (
    <div className="page-stack">
      <ErrorBoundaryPanel title="情报快照读取失败" detail="没有证据的数据不会作为事件事实展示。" />
      <button className="secondary-button" type="button" onClick={reset}>重试只读请求</button>
    </div>
  );
}
