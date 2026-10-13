import { expect, test } from "@playwright/test";

test("planner creates, edits, completes, and deletes an action item", async ({ page }) => {
  let items: Array<Record<string, unknown>> = [];
  let revision = 1;
  const response = () => ({ json: { items, total: items.length } });

  await page.route("**/api/v1/auth/me", (route) => route.fulfill({
    json: { account: { id: "owner-1", username: "planner", display_name: "Planner" }, csrf_token: "csrf" },
  }));
  await page.route("**/api/v1/action-items**", async (route) => {
    const request = route.request();
    if (request.method() === "GET") return route.fulfill(response());
    if (request.method() === "POST") {
      const body = request.postDataJSON() as Record<string, unknown>;
      items = [{
        id: "task-1", title: body.title, description: body.description ?? null,
        status: "next", priority: body.priority ?? "normal", due_date: body.due_date ?? null,
        source_type: null, source_id: null, revision, created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      }];
      return route.fulfill({ status: 201, json: items[0] });
    }
    if (request.method() === "PATCH") {
      const body = request.postDataJSON() as Record<string, unknown>;
      items = [{ ...items[0], ...body, revision: ++revision }];
      return route.fulfill({ json: items[0] });
    }
    if (request.method() === "DELETE") {
      items = [];
      return route.fulfill({ status: 204, body: "" });
    }
    return route.fulfill({ status: 405 });
  });

  await page.goto("/action-items");
  await page.getByLabel("Title").fill("Send project notes");
  await page.getByLabel("Details").fill("Share the follow-up with the team");
  await page.getByRole("button", { name: "Add to planner" }).click();
  await expect(page.getByText("Send project notes")).toBeVisible();

  await page.getByRole("button", { name: "Edit Send project notes" }).click();
  await page.getByLabel("Title").fill("Send final project notes");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(page.getByText("Send final project notes")).toBeVisible();

  await page.getByLabel("Status for Send final project notes").selectOption("done");
  await page.getByRole("button", { name: "Delete Send final project notes" }).click();
  await expect(page.getByText("Your planner is ready when you are.")).toBeVisible();
});
