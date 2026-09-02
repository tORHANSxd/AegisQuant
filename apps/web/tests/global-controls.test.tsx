import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const push = vi.fn();
const replace = vi.fn();

vi.mock("next/navigation", () => ({
  usePathname: () => "/overview",
  useRouter: () => ({ push, replace }),
  useSearchParams: () => new URLSearchParams(),
}));

import { GlobalControls } from "../src/components/global-controls";

describe("GlobalControls", () => {
  beforeEach(() => {
    push.mockReset();
    replace.mockReset();
    localStorage.clear();
  });

  it("writes only whitelisted filters to the current URL", () => {
    render(<GlobalControls />);
    fireEvent.change(screen.getByLabelText("时区"), { target: { value: "UTC" } });
    expect(replace).toHaveBeenCalledWith("/overview?timezone=UTC");
  });

  it("supports the keyboard command palette", () => {
    render(<GlobalControls />);
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(screen.getByRole("dialog", { name: "只读命令面板" })).toBeVisible();
    fireEvent.change(screen.getByLabelText("搜索页面"), { target: { value: "风险" } });
    expect(screen.getByRole("link", { name: "风险/risk" })).toHaveAttribute(
      "href",
      "/risk",
    );
  });

  it("rejects external saved targets and strips unsafe query keys", () => {
    const { rerender } = render(<GlobalControls />);
    localStorage.setItem(
      "aegisquant-safe-layout-v1",
      JSON.stringify({ pathname: "https://evil.example", query: "timezone=UTC" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "恢复布局" }));
    expect(push).not.toHaveBeenCalled();

    localStorage.setItem(
      "aegisquant-safe-layout-v1",
      JSON.stringify({ pathname: "/risk", query: "timezone=UTC&token=secret" }),
    );
    rerender(<GlobalControls />);
    fireEvent.click(screen.getByRole("button", { name: "恢复布局" }));
    expect(push).toHaveBeenCalledWith("/risk?timezone=UTC");
  });
});
