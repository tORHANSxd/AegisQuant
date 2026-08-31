import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import HomePage from "../app/page";

describe("P00 locked page", () => {
  it("shows the immutable development and Live lock state", () => {
    render(<HomePage />);

    expect(screen.getByText("DEVELOPMENT")).toBeVisible();
    expect(screen.getByText("LIVE LOCKED")).toBeVisible();
    expect(screen.getByText("真实订单提交已禁用")).toBeVisible();
  });

  it("does not expose trading or unlock controls", () => {
    render(<HomePage />);

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
