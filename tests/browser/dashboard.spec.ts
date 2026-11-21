import { test, expect } from "@playwright/test";
import fs from "node:fs";
const evidence = "/tmp/lean-observatory-qa";
test.beforeAll(() => fs.mkdirSync(evidence, { recursive: true }));
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("lean-theme", "dark"));
});
test.beforeEach(async ({ request }) => {
  const { run } = await (await request.get("/api/state")).json();
  if (
    run.id &&
    [
      "running",
      "queued",
      "paused",
      "failed",
      "interrupted",
      "resource_exhausted",
    ].includes(run.status)
  )
    await request.post("/api/control", {
      data: { run: run.id, action: "cancel" },
    });
});
async function start(request: any, scenario = "success") {
  const res = await request.post("/api/runs", {
    data: { mode: "mock", scenario },
  });
  expect(res.status()).toBe(201);
  return res.json();
}

test("desktop full dashboard, navigation, theme, logs and downloads", async ({
  page,
  request,
}) => {
  const errors: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error" || m.type() === "warning")
      errors.push(m.type() + ": " + m.text());
  });
  page.on("pageerror", (e) => errors.push(e.message));
  const s = await start(request);
  await page.setViewportSize({ width: 1600, height: 1100 });
  await page.goto("/");
  await expect(page).toHaveTitle(/Lean Observatory/);
  await expect(
    page.getByRole("heading", { name: "黎曼猜想 · 独立验证" }),
  ).toBeVisible();
  await expect(page.getByText("SSE 已连接")).toBeVisible();
  await expect(
    page.getByText("本地模拟数据，不代表真实证明结果"),
  ).toBeVisible();
  await expect
    .poll(async () => {
      const p = await (await request.get("/api/state")).json();
      return p.run.phase;
    })
    .toBe("compile");
  await expect(page.locator(".module-line")).toContainText("MockModule");
  await expect(page.locator(".compile-panel .chart-series-path")).toBeVisible();
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(0);
  await page.screenshot({
    path: evidence + "/desktop-dark.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.getByRole("button", { name: "暂停任务", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "恢复任务", exact: true }),
  ).toBeVisible();
  const paused = await (await request.get("/api/state")).json();
  await page.getByRole("button", { name: "切换浅色主题" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.screenshot({
    path: evidence + "/desktop-light.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.getByRole("link", { name: "证明审计", exact: true }).click();
  await page
    .getByRole("button", { name: "riemannHypothesis", exact: true })
    .click();
  await expect(page.getByText("期望类型：")).toBeVisible();
  for (const name of [
    "服务器监控",
    "验证时间线",
    "结果中心",
    "编译监控",
    "总览",
  ]) {
    await page.getByRole("link", { name, exact: true }).click();
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  }
  await page.getByRole("textbox", { name: "筛选实时日志" }).fill("NO_MATCH");
  await expect(page.getByText("当前窗口没有匹配日志")).toBeVisible();
  await page.getByRole("textbox", { name: "筛选实时日志" }).fill("");
  const report = await (
    await request.get("/api/report.json?run=" + s.id)
  ).json();
  expect(report.run.mode).toBe("mock");
  expect(report.run.proofAccepted).toBe(false);
  await page.getByRole("button", { name: "恢复任务", exact: true }).click();
  await expect
    .poll(
      async () => {
        return (await (await request.get("/api/state")).json()).run.status;
      },
      { timeout: 20000 },
    )
    .toBe("checks_completed");
  expect(errors).toEqual([]);
});

for (const scenario of ["failure", "interruption", "resource"])
  test(`${scenario} failure states persist and resume`, async ({
    page,
    request,
  }) => {
    await start(request, scenario);
    await page.goto("/");
    const expected = {
      failure: "failed",
      interruption: "interrupted",
      resource: "resource_exhausted",
    }[scenario];
    await expect
      .poll(
        async () => (await (await request.get("/api/state")).json()).run.status,
        { timeout: 20000 },
      )
      .toBe(expected);
    await expect(page.getByRole("alert")).toBeVisible();
    const before = (await (await request.get("/api/state")).json()).run.compile
      .succeeded;
    await page.reload();
    await expect(
      page.getByRole("button", { name: "恢复任务", exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "恢复任务", exact: true }).click();
    await expect
      .poll(
        async () => (await (await request.get("/api/state")).json()).run.status,
        { timeout: 20000 },
      )
      .toBe("checks_completed");
    const after = (await (await request.get("/api/state")).json()).run;
    expect(after.compile.succeeded).toBeGreaterThanOrEqual(before);
    expect(after.proofAccepted).toBe(false);
  });

for (const width of [320, 390, 768, 1280])
  test(`responsive ${width}px and mobile navigation`, async ({
    page,
    request,
  }) => {
    await start(request);
    await page.setViewportSize({ width, height: width < 700 ? 844 : 900 });
    await page.goto("/");
    await expect(page.getByText("SSE 已连接")).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    if (width < 700) {
      await page.getByRole("button", { name: "打开导航" }).click();
      await page.getByRole("link", { name: "结果中心", exact: true }).click();
      await expect(
        page.getByRole("heading", { name: "结果中心", exact: true }),
      ).toBeVisible();
    }
    await expect
      .poll(async () => {
        return (
          width >= 700 ||
          !(await page.getByRole("navigation", { name: "主导航" }).isVisible())
        );
      })
      .toBe(true);
    await page.screenshot({
      path: `${evidence}/responsive-${width}.png`,
      fullPage: true,
      animations: "disabled",
    });
  });

test("SSE disconnect reconnect and live data recovery", async ({
  page,
  request,
  context,
}) => {
  await start(request);
  await page.goto("/");
  await expect(page.getByText("SSE 已连接")).toBeVisible();
  await context.setOffline(true);
  await expect(page.getByText("断线重连中")).toBeVisible({ timeout: 10000 });
  await context.setOffline(false);
  await expect(page.getByText("SSE 已连接")).toBeVisible({ timeout: 15000 });
});

test("new task dialog and real gate", async ({ page, request }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "新建任务" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  const real = page.locator('option[value="real"]');
  await expect(real).toBeDisabled();
  await page.getByLabel("模拟场景").selectOption("failure");
  await page.getByRole("button", { name: "创建并开始" }).click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await expect(page.getByText("SSE 已连接")).toBeVisible();
});
