import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

import { expect, test } from "@playwright/test";

test("overview is read-only, traceable, and visually stable", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/overview$/);
  await expect(page.getByRole("heading", { name: "账户与风险总览" })).toBeVisible();
  await expect(page.getByText("LIVE TRADING LOCKED")).toBeVisible();
  await expect(page.getByText("VIEWER · READ ONLY")).toBeVisible();
  await expect(page.getByText("10,001.89")).toBeVisible();
  await expect(page.getByText(/历史开发快照/).first()).toBeVisible();
  await expect(page.locator("input[type=password]")).toHaveCount(0);
  await expect(page.getByText(/提交订单|解锁实盘|API Secret/i)).toHaveCount(0);
  const response = await page.request.get("/overview");
  expect(response.headers()["content-security-policy"]).toContain("frame-ancestors 'none'");
  await expect(page).toHaveScreenshot("overview.png", { fullPage: true, animations: "disabled" });
});

test("intelligence links events to evidence and source policy", async ({ page }) => {
  await page.goto("/intelligence");
  await expect(page.getByRole("heading", { name: "全球事件与叙事情报" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "事件雷达" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "证据关系" })).toBeVisible();
  await expect(page.getByText(/全文受限，仅显示证据 ID/).first()).toBeVisible();
  await expect(page.getByText(/不能直接生成订单/)).toBeVisible();
});

test("overview responsive layout remains usable on a narrow viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/overview");
  await expect(page.getByRole("navigation", { name: "主导航" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "账户与风险总览" })).toBeVisible();
  await expect(page.locator("body")).not.toHaveCSS("overflow-x", "scroll");
});

test("warm local overview p75 stays below 1.5 seconds", async ({ page }) => {
  await page.goto("/overview");
  const samples: number[] = [];
  for (let index = 0; index < 5; index += 1) {
    const started = Date.now();
    await page.reload({ waitUntil: "domcontentloaded" });
    samples.push(Date.now() - started);
  }
  samples.sort((left, right) => left - right);
  const p75Ms = samples[3];
  const evidenceDirectory = resolve(process.cwd(), "../../reports/performance");
  await mkdir(evidenceDirectory, { recursive: true });
  await writeFile(
    resolve(evidenceDirectory, "P14_OVERVIEW_BENCHMARK.json"),
    `${JSON.stringify({
      schema_version: "1.0.0",
      phase: "P14",
      environment: "local-production-loopback",
      metric: "overview_domcontentloaded_ms",
      samples_ms: samples,
      p75_ms: p75Ms,
      target_p75_ms: 1500,
      status: p75Ms < 1500 ? "passed" : "failed",
      qualifies_as_12h_or_24h_acceptance: false,
    }, null, 2)}\n`,
    "utf8",
  );
  expect(p75Ms).toBeLessThan(1500);
});
