import { defineConfig } from "@playwright/test";
import { existsSync } from "node:fs";
const localChromium =
  "/Users/tano/Library/Caches/ms-playwright/chromium-1255/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing";
export default defineConfig({
  testDir: "tests/browser",
  fullyParallel: false,
  workers: 1,
  timeout: 45000,
  reporter: [["list"]],
  outputDir: "/tmp/lean-observatory-browser-results",
  use: {
    baseURL: "http://127.0.0.1:8788",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    launchOptions: {
      executablePath:
        process.env.CHROMIUM_PATH ||
        (existsSync(localChromium) ? localChromium : undefined),
    },
  },
  webServer: {
    command:
      "python3 scripts/local.py --port 8788 --data /tmp/lean-observatory-e2e --interval 0.15",
    url: "http://127.0.0.1:8788/healthz",
    reuseExistingServer: false,
    timeout: 15000,
  },
});
