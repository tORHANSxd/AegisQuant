import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ usePathname: () => "/overview" }));
vi.mock("../src/components/realtime-status", () => ({
  RealtimeStatus: () => <span>STREAM DISCONNECTED</span>,
}));
vi.mock("../src/components/preferences", () => ({
  PreferenceControls: () => <span>显示偏好</span>,
}));

import { AppShell } from "../src/components/app-shell";

describe("P14 read-only app shell", () => {
  it("shows environment, permission, and immutable Live lock", () => {
    render(<AppShell><p>内容</p></AppShell>);

    expect(screen.getByText("RESEARCH ENVIRONMENT")).toBeVisible();
    expect(screen.getByText("LIVE TRADING LOCKED")).toBeVisible();
    expect(screen.getByText("VIEWER · READ ONLY")).toBeVisible();
    expect(screen.getByRole("link", { name: "总览" })).toHaveAttribute("aria-current", "page");
  });

  it("contains no trading, credential, or unlock controls", () => {
    render(<AppShell><p>内容</p></AppShell>);

    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByText(/提交订单|解锁实盘|API Secret/i)).not.toBeInTheDocument();
  });
});
