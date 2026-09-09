import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright E2E configuration.
 *
 * By default the tests assume the Next.js dev server is already running on
 * port 3000 and the FastAPI backend on port 8000.  Set the `BASE_URL`
 * environment variable to override.
 *
 * Run:  pnpm test:e2e          (headless)
 *       pnpm test:e2e:ui       (interactive UI mode)
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [["html", { open: "never" }]],

  use: {
    baseURL: process.env.BASE_URL ?? "http://localhost:3000",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],

  /* Start the Next.js dev server automatically when running E2E tests */
  webServer: {
    command: "pnpm dev",
    url: "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
});
