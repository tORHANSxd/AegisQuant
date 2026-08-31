import { expect, test } from "@playwright/test";

test("renders the P00 safety state without controls", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByText("DEVELOPMENT", { exact: true })).toBeVisible();
  await expect(page.getByText("LIVE LOCKED", { exact: true })).toBeVisible();
  await expect(page.getByRole("button")).toHaveCount(0);
  await expect(page.getByRole("textbox")).toHaveCount(0);
});
