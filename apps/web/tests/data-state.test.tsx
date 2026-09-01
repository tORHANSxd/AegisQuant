import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DataState, type DataStateKind } from "../src/components/data-state";

describe("DataState", () => {
  it.each<[DataStateKind, string]>([
    ["LOADING", "正在读取服务端快照"],
    ["EMPTY", "暂无数据"],
    ["STALE", "数据陈旧"],
    ["DEGRADED", "降级运行"],
    ["DISCONNECTED", "连接中断"],
    ["ERROR", "读取失败"],
    ["PERMISSION_DENIED", "无权查看"],
  ])("renders %s explicitly", (state, label) => {
    render(<DataState state={state} reason="测试原因"><span>payload</span></DataState>);
    expect(screen.getAllByText(new RegExp(label))[0]).toBeVisible();
  });

  it("shows complete provenance for live data", () => {
    render(
      <DataState
        state="LIVE"
        asOf="2026-09-01T21:50:00Z"
        latencyMs={42}
        source="verified.json"
        authoritative
        estimated={false}
        lastSuccessAt="2026-09-01T21:50:01Z"
      >
        <span>payload</span>
      </DataState>,
    );
    expect(screen.getByText("payload")).toBeVisible();
    expect(screen.getByText(/42 ms/)).toBeVisible();
    expect(screen.getByText(/verified.json/)).toBeVisible();
    expect(screen.getByText("权威口径")).toBeVisible();
    expect(screen.getByText("非估算")).toBeVisible();
  });
});
