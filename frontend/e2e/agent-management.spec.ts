import { expect, test } from "./fixtures";

test("agent prompts and reusable specialists can be managed from settings", async ({ page }) => {
  const chatAgent = {
    name: "chat",
    display_name: "Chat",
    target: "chat",
    description: "General conversation",
    default_for_target: true,
    system_prompt: "Default chat prompt",
    is_custom: false,
    archived: false,
    inference: { allowed_models: ["llama3.1:8b"], defaults: { model: "llama3.1:8b", temperature: 0.7 } },
  };
  const profiles = [chatAgent];
  const catalog = (includeArchived: boolean) => ({
    agents: profiles.filter((agent) => includeArchived || !agent.archived),
  });

  await page.route("**/api/v1/agents**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const includeArchived = url.searchParams.get("include_archived") === "true";

    if (request.method() === "GET") {
      return route.fulfill({ json: catalog(includeArchived) });
    }

    if (request.method() === "POST") {
      const body = request.postDataJSON() as {
        source_agent: string;
        display_name: string;
        description: string;
      };
      const source = profiles.find((agent) => agent.name === body.source_agent);
      if (!source) return route.fulfill({ status: 422, json: { detail: "Unknown source agent" } });
      const created = {
        ...source,
        name: body.display_name.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, ""),
        display_name: body.display_name,
        description: body.description,
        default_for_target: false,
        is_custom: true,
        archived: false,
      };
      profiles.push(created);
      return route.fulfill({ json: catalog(true) });
    }

    if (request.method() === "PATCH") {
      const name = decodeURIComponent(url.pathname.split("/").pop() ?? "");
      const profile = profiles.find((agent) => agent.name === name);
      if (!profile) return route.fulfill({ status: 404, json: { detail: "Not found" } });
      Object.assign(profile, request.postDataJSON());
      return route.fulfill({ json: catalog(true) });
    }

    return route.fulfill({ status: 405 });
  });

  await page.route("**/api/v1/health", (route) => route.fulfill({
    json: { status: "healthy", services: [], meeting_ready: false },
  }));
  await page.route("**/api/v1/tools", (route) => route.fulfill({ json: { tools: [] } }));
  await page.route("**/api/v1/github/connection", (route) => route.fulfill({
    json: { connected: false, configured: false, login: null, expires_at: null, install_url: null },
  }));

  await page.goto("/settings");
  const prompt = page.getByLabel("System prompt");
  await expect(prompt).toHaveValue("Default chat prompt");
  await prompt.fill("Answer with concise project updates.");
  await page.getByRole("button", { name: "Save prompt" }).click();
  await expect(page.getByRole("status")).toHaveText("Agent saved. Changes apply to the next request.");

  await page.getByLabel("Name").fill("Project Researcher");
  await page.getByRole("combobox", { name: "Copy from" }).click();
  await page.getByRole("option", { name: "Chat" }).click();
  await page.getByLabel("Description").fill("Research project background");
  await page.getByRole("button", { name: "Create agent" }).click();
  await expect(page.getByRole("status")).toHaveText("Agent created.");
  await expect(page.getByRole("combobox", { name: "Agent", exact: true })).toContainText("Project Researcher");
  await expect(prompt).toHaveValue("Answer with concise project updates.");

  await prompt.fill("Research carefully and cite source material.");
  await page.getByLabel("Name").first().fill("Project Researcher Plus");
  await page.getByLabel("Description").first().fill("Research projects and cite findings");
  await page.getByRole("button", { name: "Save prompt" }).click();
  await expect(page.getByRole("status")).toHaveText("Agent saved. Changes apply to the next request.");
  await expect(page.getByLabel("Name").first()).toHaveValue("Project Researcher Plus");

  await page.getByRole("button", { name: "Archive agent" }).click();
  await expect(page.getByRole("status")).toHaveText("Agent archived.");
  await expect(page.getByRole("button", { name: "Restore agent" })).toBeVisible();
  await page.getByRole("button", { name: "Restore agent" }).click();
  await expect(page.getByRole("status")).toHaveText("Agent restored.");

  await page.goto("/chat");
  await page.getByRole("combobox", { name: "Agent profile" }).click();
  await expect(page.getByRole("option", { name: "Project Researcher Plus" })).toBeVisible();
});
