import { defineConfig } from "@playwright/test";

// End-to-end tests against a running app (python manage.py dev). Locally they use the installed Edge
// (no browser download); set PW_CHANNEL=chromium in CI after `npx playwright install chromium`.
export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 20_000 },
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:5174",
    channel: process.env.PW_CHANNEL === "chromium" ? undefined : (process.env.PW_CHANNEL ?? "msedge"),
    viewport: { width: 1400, height: 900 },
  },
});
