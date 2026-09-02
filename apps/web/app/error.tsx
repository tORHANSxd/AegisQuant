"use client";

import { ErrorBoundaryPanel } from "../src/components/data-state";

export default function RouteError({ reset }: Readonly<{ reset: () => void }>) {
  return (
    <div className="page-stack">
      <ErrorBoundaryPanel
        title="当前页面读取失败"
        detail="故障已限制在当前路由；侧栏和其他只读页面仍可使用，系统不会把旧数据冒充实时状态。"
      />
      <button className="secondary-button" type="button" onClick={reset}>重试当前只读请求</button>
    </div>
  );
}
