import { test, expect } from "./fixtures";

/**
 * Smoke tests that verify the Next.js frontend loads and the key pages
 * render without crashing.  These do NOT require the backend to be running —
 * they only check client-side rendering.
 */

test.describe("Navigation smoke tests", () => {
  test("dashboard page loads", async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveTitle(/Local AI/i);
    // The sidebar should be present
    await expect(page.locator('[data-sidebar="sidebar"]')).toBeVisible();
  });

  test("chat page loads", async ({ page }) => {
    await page.goto("/chat");
    // Should show the Chat heading in the header
    await expect(page.locator("header")).toContainText("Chat");
  });

  test("documents page loads", async ({ page }) => {
    await page.goto("/documents");
    await expect(page.locator("header")).toContainText("Documents");
  });

  test("sql page loads", async ({ page }) => {
    await page.goto("/sql");
    await expect(page.locator("header")).toContainText("SQL Agent");
  });

  test("rag page loads", async ({ page }) => {
    await page.goto("/rag");
    await expect(page.locator("header")).toContainText("RAG Search");
  });

  test("settings page loads", async ({ page }) => {
    await page.goto("/settings");
    await expect(page.locator("header")).toContainText("Settings");
    // The system health card should be visible
    await expect(page.getByText("System Health")).toBeVisible();
  });
});

test.describe("Sidebar navigation", () => {
  test("can navigate between pages via sidebar links", async ({ page }) => {
    await page.goto("/");

    // Click the Chat link in the sidebar
    const chatLink = page.locator('[data-sidebar="sidebar"]').getByRole("link", { name: /chat/i });
    await expect(chatLink).toBeVisible();
    await chatLink.click();
    await expect(page).toHaveURL(/\/chat/);
    await expect(page.locator("header")).toContainText("Chat");
  });
});

test.describe("Theme toggle", () => {
  test("theme toggle button is visible in the header", async ({ page }) => {
    await page.goto("/");
    // The theme toggle is a button inside the header
    const header = page.locator("header");
    await expect(header).toBeVisible();
    // There should be at least one button (sidebar trigger + theme toggle)
    const buttons = header.getByRole("button");
    await expect(buttons.first()).toBeVisible();
  });
});

test.describe("Settings page functionality", () => {
  test("shows appearance section with theme buttons", async ({ page }) => {
    await page.goto("/settings");
    await expect(page.getByText("Appearance")).toBeVisible();
    await expect(page.getByRole("button", { name: /light/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /dark/i })).toBeVisible();
    await expect(page.getByRole("button", { name: /system/i })).toBeVisible();
  });

  test("shows database connection form", async ({ page }) => {
    await page.goto("/settings");
    await expect(page.getByText("Database Connections")).toBeVisible();
    await expect(page.getByRole("button", { name: /add connection/i })).toBeVisible();
  });
});

test("chat profile selector exposes matching specialist inputs", async ({ page }) => {
  await page.route("**/api/v1/agents**", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      agents: [{
        name: "stock_research",
        target: "stock_research",
        description: "Research equities",
        default_for_target: true,
        inference: {
          allowed_models: ["qwen2.5:7b"],
          defaults: {
            model: "qwen2.5:7b",
            temperature: 0.2,
          },
          limits: { temperature: { minimum: 0, maximum: 2 } },
        },
      }],
    }),
  }));

  await page.goto("/chat");
  await page.getByRole("combobox", { name: "Agent profile" }).click();
  await page.getByRole("option", { name: /Stock Research/ }).click();
  await page.getByRole("button", { name: "Options" }).click();
  await expect(page.getByLabel("Ticker symbol")).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Agent model" })).toContainText("qwen2.5:7b");
});
