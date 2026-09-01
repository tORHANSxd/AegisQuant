import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { PreferenceControls } from "../src/components/preferences";

describe("PreferenceControls", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
      callback(0);
      return 1;
    });
    vi.stubGlobal("cancelAnimationFrame", () => undefined);
  });

  it("persists only display preferences on this device", async () => {
    render(<PreferenceControls />);
    fireEvent.change(screen.getByLabelText("主题"), { target: { value: "light" } });
    fireEvent.change(screen.getByLabelText("涨跌色"), { target: { value: "red-up" } });
    fireEvent.click(screen.getByLabelText("高对比"));

    await waitFor(() => expect(document.documentElement.dataset.theme).toBe("light"));
    expect(document.documentElement.dataset.marketColors).toBe("red-up");
    expect(document.documentElement.dataset.contrast).toBe("high");
    const stored = localStorage.getItem("aegisquant-ui-preferences-v1") ?? "";
    expect(stored).not.toMatch(/secret|password|token/i);
  });
});
