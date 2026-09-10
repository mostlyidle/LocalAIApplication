import { test, expect } from "@playwright/test";

// Browser regressions use backend wire shapes. The backend contract test separately
// sends real HTTP responses through these same frontend validators.
test("newly uploaded documents can be listed and analyzed", async ({ page }) => {
  const document = {
    id: "doc-1", filename: "notes.txt", format: "text", size_bytes: 128,
    status: "pending", created_at: "2026-09-10T00:00:00Z",
  };
  let uploaded = false;
  await page.route("**/api/v1/documents", (route) => route.fulfill({ json: uploaded ? [document] : [] }));
  await page.route("**/api/v1/documents/upload", (route) => {
    uploaded = true;
    return route.fulfill({ json: document });
  });
  await page.route("**/api/v1/documents/doc-1/analyze", (route) => route.fulfill({
    json: {
      document_id: "doc-1", filename: "notes.txt", format: "text",
      text: "Meeting notes extracted successfully.", tables: [], metadata: {},
      page_count: 1, word_count: 4, status: "completed",
    },
  }));
  await page.goto("/documents");
  await page.locator('input[type="file"]').setInputFiles({
    name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("Meeting notes"),
  });
  await expect(page.getByText("notes.txt", { exact: true })).toBeVisible();
  await expect(page.getByText("128 B", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Analyze", exact: true }).click();
  await expect(page.getByText("Meeting notes extracted successfully.")).toBeVisible();
  await expect(page.getByText("completed", { exact: true })).toBeVisible();
});

test("SQL sends the question and selected connection and displays both result formats", async ({ page }) => {
  await page.route("**/api/v1/sql/connections", (route) => route.fulfill({
    json: [{ name: "secondary", url: "sqlite+aiosqlite:///demo.db" }],
  }));
  await page.route("**/api/v1/sql/schema*", (route) => route.fulfill({ json: { database: "secondary", tables: [] } }));
  await page.route("**/api/v1/sql/query", (route) => route.fulfill({
    json: {
      question: "Show customers", generated_sql: "SELECT name FROM customers",
      columns: ["name"], rows: [["Ada"]], row_count: 1,
      explanation: "One customer.", execution_time_ms: 1,
    },
  }));
  await page.route("**/api/v1/sql/execute", (route) => route.fulfill({
    json: { sql: "SELECT 42", result: { columns: ["value"], rows: [[42]], row_count: 1 }, execution_time_ms: 1 },
  }));
  await page.goto("/sql");
  await page.getByLabel("Database connection").selectOption("secondary");
  await page.getByPlaceholder("e.g. Show me the top 5 customers by total spending").fill("Show customers");
  const questionRequest = page.waitForRequest("**/api/v1/sql/query");
  await page.getByRole("button", { name: "Ask AI" }).click();
  expect((await questionRequest).postDataJSON()).toEqual({ question: "Show customers", database: "secondary" });
  await expect(page.getByRole("cell", { name: "Ada", exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "Raw SQL" }).click();
  await page.getByPlaceholder("SELECT * FROM customers LIMIT 10;").fill("SELECT 42");
  const sqlRequest = page.waitForRequest("**/api/v1/sql/execute");
  await page.getByRole("button", { name: "Execute", exact: true }).click();
  expect((await sqlRequest).postDataJSON()).toEqual({ sql: "SELECT 42", database: "secondary" });
  await expect(page.getByRole("cell", { name: "42", exact: true })).toBeVisible();
});
