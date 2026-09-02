import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";

import { expect, test } from "@playwright/test";

const routes = [
  ["/overview", "账户与风险总览"],
  ["/live", "实时台与状态回放"],
  ["/performance", "绩效、成本与归因"],
  ["/execution", "执行质量与订单追溯"],
  ["/strategies", "策略目录与信号"],
  ["/models", "模型评估与治理"],
  ["/market", "市场状态与历史回放"],
  ["/intelligence", "全球事件与叙事情报"],
  ["/risk", "风险限额与熔断姿态"],
  ["/research", "研究运行与负结果"],
  ["/research/intelligence", "外部知识与情报研究"],
  ["/data", "数据质量、来源与血缘"],
  ["/incidents", "事故时间线与恢复证据"],
  ["/system", "系统健康与契约状态"],
  ["/settings", "安全设置"],
] as const;

test("all P15 routes remain read-only and expose their core state", async ({ page }) => {
  for (const [route, heading] of routes) {
    await page.goto(route, { waitUntil: "domcontentloaded" });
    await expect(page.getByRole("heading", { name: heading })).toBeVisible();
    await expect(page.getByText("LIVE TRADING LOCKED")).toBeVisible();
    await expect(page.locator("input[type=password]")).toHaveCount(0);
    await expect(page.getByRole("button", { name: /提交订单|解锁实盘|发布模型|修改限额/i })).toHaveCount(0);
  }
});

test("overview exposes PnL formula, provenance, reconciliation, and stable visual", async ({ page }) => {
  await page.goto("/overview");
  await expect(page.getByText("10,001.89", { exact: true })).toBeVisible();
  await expect(page.getByText("SYNCHRONIZED")).toBeVisible();
  await expect(page.getByText(/gross_trading_pnl - trading_fees/)).toBeVisible();
  await expect(page.getByText(/来源 reports\/backtests\/p06-golden\/pnl_attribution/)).toBeVisible();
  await expect(page.getByText(/数据截至/)).toBeVisible();
  await expect(page.locator(".chart-canvas canvas").first()).toBeVisible();
  const response = await page.request.get("/overview");
  expect(response.headers()["content-security-policy"]).toContain("frame-ancestors 'none'");
  await expect(page).toHaveScreenshot("p15-overview.png", { fullPage: true, animations: "disabled" });
});

test("every visible order opens a complete seven-stage trace", async ({ page }) => {
  await page.goto("/execution");
  const links = page.getByRole("link", { name: "查看完整链" });
  await expect(links.first()).toBeVisible();
  const orderCount = await links.count();
  expect(orderCount).toBeGreaterThan(0);

  for (let index = 0; index < orderCount; index += 1) {
    const href = await links.nth(index).getAttribute("href");
    expect(href).toBeTruthy();
    const detail = await page.context().newPage();
    await detail.goto(href!);
    await expect(detail.getByRole("heading", { name: "订单完整决策链" })).toBeVisible();
    await expect(detail.locator(".trace-stage-list > li")).toHaveCount(7);
    await expect(detail.getByText("COMPLETE")).toBeVisible();
    await expect(detail.getByText("schema 强制 false")).toBeVisible();
    await detail.close();
  }

  await expect(page.locator(".chart-canvas canvas").first()).toBeVisible();
  await expect(page).toHaveScreenshot("p15-execution.png", { fullPage: true, animations: "disabled" });
});

test("global filters, command palette, export, and local layout are functional", async ({ page }) => {
  await page.goto("/performance");
  await expect(page.locator(".global-controls")).toHaveAttribute("data-ready", "true");
  await page.locator(".global-controls").getByLabel("时区").selectOption("UTC");
  await expect(page).toHaveURL(/timezone=UTC/);
  await expect(page.getByText(/数据截至 · UTC/)).toBeVisible();

  await page.keyboard.press("Control+K");
  await expect(page.getByRole("dialog", { name: "只读命令面板" })).toBeVisible();
  await page.getByLabel("搜索页面").fill("事故");
  await expect(page.getByRole("dialog").getByRole("link", { name: /事故/ })).toBeVisible();
  await page.keyboard.press("Escape");

  await page.getByRole("button", { name: "保存布局" }).click();
  await page.goto("/overview");
  await page.getByRole("button", { name: "恢复布局" }).click();
  await expect(page).toHaveURL(/\/performance\?.*timezone=UTC/);

  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出" }).click();
  expect((await download).suggestedFilename()).toMatch(/^aegisquant-performance\.txt$/);
});

test("color semantics remain stable across routes and settings stay local", async ({ page }) => {
  await page.goto("/overview");
  const overviewColors = await page.evaluate(() => {
    const style = getComputedStyle(document.documentElement);
    return [style.getPropertyValue("--green"), style.getPropertyValue("--red")];
  });
  await page.goto("/risk");
  const riskColors = await page.evaluate(() => {
    const style = getComputedStyle(document.documentElement);
    return [style.getPropertyValue("--green"), style.getPropertyValue("--red")];
  });
  expect(riskColors).toEqual(overviewColors);

  await page.goto("/settings");
  await expect(page.getByText("未连接")).toBeVisible();
  await expect(page.getByText("不接收、不保存")).toBeVisible();
  await expect(page.locator("input[type=password]")).toHaveCount(0);
});

test("narrow viewport has no body-level horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/overview");
  await expect(page.getByRole("navigation", { name: "主导航" })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test("warm local workbench p75 stays below 1.5 seconds", async ({ page, browserName }) => {
  test.skip(browserName !== "chromium", "性能证据固定使用 Chromium，避免多项目并发改写同一工件。");
  await page.goto("/overview");
  const samples: number[] = [];
  for (let index = 0; index < 5; index += 1) {
    const started = Date.now();
    await page.reload({ waitUntil: "domcontentloaded" });
    samples.push(Date.now() - started);
  }
  samples.sort((left, right) => left - right);
  const p75Ms = samples[3];
  if (process.env.UPDATE_P15_BENCHMARK === "1") {
    const evidenceDirectory = resolve(process.cwd(), "../../reports/performance");
    await mkdir(evidenceDirectory, { recursive: true });
    await writeFile(
      resolve(evidenceDirectory, "P15_WORKBENCH_BENCHMARK.json"),
      `${JSON.stringify({
        schema_version: "1.0.0",
        phase: "P15",
        environment: "local-production-loopback",
        metric: "workbench_domcontentloaded_ms",
        samples_ms: samples,
        p75_ms: p75Ms,
        target_p75_ms: 1500,
        status: p75Ms < 1500 ? "passed" : "failed",
        qualifies_as_12h_or_24h_acceptance: false,
      }, null, 2)}\n`,
      "utf8",
    );
  }
  expect(p75Ms).toBeLessThan(1500);
});
