import { expect, test as base } from "@playwright/test";

export const test = base.extend({
  page: async ({ page }, use) => {
    await page.route("**/api/v1/auth/me", (route) => route.fulfill({
      json: {
        account: { id: "e2e-user", username: "e2e", display_name: "E2E User" },
        csrf_token: "e2e-csrf",
      },
    }));
    await use(page);
  },
});

export { expect };
