import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
const evidence = "/tmp/lean-observatory-chart-qa";
test.beforeAll(() => fs.mkdirSync(evidence, { recursive: true }));
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("lean-theme", "dark"));
});
test.beforeEach(() =>
  execFileSync("python3", [
    "scripts/seed_demo.py",
    "--data",
    "/tmp/lean-observatory-e2e",
    "--seconds",
    "45",
    "--slowdown",
    "30",
    "--tick-seconds",
    ".15",
  ]),
);

test("all chart geometry is undistorted and supports pointer and keyboard inspection", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/");
  await expect(
    page.locator(".compile-panel .chart-series-path").first(),
  ).toBeVisible();
  const chart = page.locator(".compile-panel .chart > svg");
  const box = await chart.boundingBox();
  await chart.hover({
    position: { x: box!.width * 0.55, y: box!.height * 0.5 },
  });
  await expect(page.locator(".compile-panel .chart-tooltip")).toContainText(
    "files/s",
  );
  await chart.focus();
  await chart.press("Home");
  const first = await page.locator(".chart-tooltip time").textContent();
  await chart.press("End");
  expect(await page.locator(".chart-tooltip time").textContent()).not.toBe(
    first,
  );
  await chart.press("Escape");
  await expect(page.locator(".chart-tooltip")).toHaveCount(0);
  await chart.evaluate((node) => (node as SVGSVGElement).blur());
  await page.mouse.move(0, 0);
  await page.screenshot({
    path: evidence + "/overview-dark.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.getByRole("link", { name: "服务器监控", exact: true }).click();
  await expect(page.locator(".server-charts-grid .panel")).toHaveCount(5);
  await expect(page.locator('[data-series="rx"]')).toBeVisible();
  await expect(page.locator('[data-series="tx"]')).toBeVisible();
  const geometry = await page.locator(".chart > svg").evaluateAll((nodes) =>
    nodes.map((n) => {
      const svg = n as SVGSVGElement,
        c = svg.getScreenCTM()!;
      return {
        ratio: c.a / c.d,
        font: parseFloat(
          getComputedStyle(svg.querySelector(".chart-tick")!).fontSize,
        ),
      };
    }),
  );
  expect(
    geometry.every((g) => Math.abs(g.ratio - 1) < 0.015 && g.font >= 10),
  ).toBe(true);
  await page.getByRole("button", { name: "1 分钟", exact: true }).click();
  await expect(page).toHaveURL(/window=60/);
  await expect(
    page.getByRole("button", { name: "1 分钟", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await page.screenshot({
    path: evidence + "/server-dark.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.getByRole("button", { name: "切换浅色主题" }).click();
  await page.screenshot({
    path: evidence + "/server-light.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.context().setOffline(true);
  await expect(page.getByText("断线重连中")).toBeVisible();
  await expect(page.locator(".metrics-toolbar .dot.live")).toHaveCount(0);
  await expect(page.getByText("采集器未更新，保留最近有效数据")).toBeVisible();
  await page.context().setOffline(false);
  await expect(page.getByText("SSE 已连接")).toBeVisible();
  await expect(page.locator(".metrics-toolbar .dot.live")).toHaveCount(1);
  expect(errors).toEqual([]);
});

test.describe("touch charts", () => {
  test.use({
    hasTouch: true,
    isMobile: true,
    viewport: { width: 390, height: 844 },
  });
  test("mobile charts stay legible, scroll freely and expose values on tap", async ({
    page,
  }) => {
    await page.goto("/#server");
    await expect(page.locator(".server-charts-grid .panel")).toHaveCount(5);
    const chart = page.locator(".server-charts-grid .chart > svg").first();
    const box = await chart.boundingBox();
    await chart.tap({
      position: { x: box!.width * 0.55, y: box!.height * 0.5 },
    });
    await expect(page.locator(".chart-tooltip")).toContainText("%");
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    const tip = await page.locator(".chart-tooltip").boundingBox();
    expect(tip!.x).toBeGreaterThanOrEqual(0);
    expect(tip!.x + tip!.width).toBeLessThanOrEqual(390);
    await page.screenshot({
      path: evidence + "/server-mobile-390.png",
      fullPage: true,
      animations: "disabled",
    });
    await page.setViewportSize({ width: 320, height: 844 });
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: evidence + "/server-mobile-320.png",
      fullPage: true,
      animations: "disabled",
    });
  });
});
