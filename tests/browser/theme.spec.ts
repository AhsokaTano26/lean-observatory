import { test, expect } from "@playwright/test";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
const evidence = "/tmp/lean-observatory-theme-qa";
test("editorial theme defaults to paper and adapts from phone to desktop", async ({
  page,
}) => {
  fs.mkdirSync(evidence, { recursive: true });
  execFileSync("python3", [
    "scripts/seed_demo.py",
    "--data",
    "/tmp/lean-observatory-e2e",
    "--seconds",
    "120",
    "--slowdown",
    "30",
    "--tick-seconds",
    ".15",
  ]);
  execFileSync("python3", [
    "-c",
    "from pathlib import Path; from backend.store import Store; s=Store(Path('/tmp/lean-observatory-e2e')); r=s.snapshot(); s.mutate(r['id'], lambda run: run['commands'].append({'stage':'mock_ui_fixture','argv':['MOCK_UI_FIXTURE','--not-executed'],'exitCode':0}), 'mock_ui_fixture')",
  ]);
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(page.locator(".chart-series-path").first()).toBeVisible();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "跳至主要内容" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#content")).toBeFocused();
  await expect(page).not.toHaveURL(/#content$/);
  await expect(page.locator(".compile-panel")).toBeVisible();
  for (const width of [320, 360, 390, 768, 1024, 1280, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await expect
      .poll(() =>
        page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
      )
      .toBe(true);
    if (width === 320) {
      await expect(page.locator(".mobile-audit-summary").first()).toBeVisible();
      await page
        .getByRole("button", { name: "riemannHypothesis", exact: true })
        .click();
      await expect(page.getByText("期望类型：")).toBeVisible();
      await page
        .getByRole("button", { name: "riemannHypothesis", exact: true })
        .click();
      await page.goto("/#results");
      await expect(
        page.getByRole("columnheader", { name: "命令参数" }),
      ).toBeVisible();
      await expect(
        page.getByRole("columnheader", { name: "退出码" }),
      ).toBeVisible();
      await expect(
        page.getByText("MOCK_UI_FIXTURE --not-executed"),
      ).toBeVisible();
      await page.goto("/");
    }
    const geometry = await page.locator(".chart > svg").evaluateAll((nodes) =>
      nodes.map((n) => {
        const svg = n as SVGSVGElement,
          c = svg.getScreenCTM()!;
        return c.a / c.d;
      }),
    );
    expect(geometry.every((r) => Math.abs(r - 1) < 0.015)).toBe(true);
    await page.screenshot({
      path: `${evidence}/overview-light-${width}.png`,
      fullPage: true,
      animations: "disabled",
    });
  }
  await page.getByRole("button", { name: "切换深色主题" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});
