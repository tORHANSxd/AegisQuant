import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("echarts", () => ({
  init: () => ({ setOption: () => undefined, resize: () => undefined, dispose: () => undefined }),
}));

class ResizeObserverStub {
  observe() {}
  disconnect() {}
}
vi.stubGlobal("ResizeObserver", ResizeObserverStub);

import { EquityChart } from "../src/components/charts/chart-suite";

describe("chart accessibility fallback", () => {
  it("renders an accessible summary and semantic data table", () => {
    render(<EquityChart points={[{ label: "09:00", value: 10000 }, { label: "10:00", value: 10001 }]} />);
    expect(screen.getByText("权益曲线")).toBeVisible();
    expect(screen.getByRole("img", { name: /服务端权益点/ })).toBeVisible();
    expect(screen.getByText("权益曲线数据表")).toBeVisible();
  });
});
