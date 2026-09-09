import { test, expect } from "@playwright/test";

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
    await expect(page.locator("aside")).toBeVisible();
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
    const chatLink = page.locator("aside").getByRole("link", { name: /chat/i });
    if (await chatLink.isVisible()) {
      await chatLink.click();
      await expect(page).toHaveURL(/\/chat/);
      await expect(page.locator("header")).toContainText("Chat");
    }
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
