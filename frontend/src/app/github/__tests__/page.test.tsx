import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const api = vi.hoisted(() => ({
  createActionItem: vi.fn(),
  createGitHubIssue: vi.fn(),
  createGitHubIssueComment: vi.fn(),
  getGitHubPullDetail: vi.fn(),
  getGitHubProjectOverview: vi.fn(),
  getGitHubRepositories: vi.fn(),
  proposeGitHubIssueActions: vi.fn(),
}));

vi.mock("@/lib/api", () => api);
vi.mock("lucide-react", () => {
  const Icon = (props: Record<string, unknown>) => <span {...props} />;
  return { ExternalLink: Icon, Github: Icon, Loader2: Icon, RefreshCw: Icon, Sparkles: Icon, ChevronDownIcon: Icon, ChevronUpIcon: Icon, CheckIcon: Icon };
});

import GitHubProjectPage from "../page";

const overview = {
  repository_id: "42",
  repository: "octocat/project",
  issues: [{
    number: 9, title: "Add indexes", body: "Add indexes before launch.", state: "open",
    html_url: "https://github.com/octocat/project/issues/9", author: "octocat",
    updated_at: "2026-10-12T10:00:00Z", labels: ["database"],
  }],
  pull_requests: [{
    number: 10, title: "Add schema index", body: "Adds the requested index.", state: "open",
    html_url: "https://github.com/octocat/project/pull/10", author: "octocat",
    updated_at: "2026-10-12T11:00:00Z", labels: [], draft: false, head_sha: "abc123",
  }],
};

describe("GitHubProjectPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getGitHubRepositories.mockResolvedValue({ repositories: [{
      repository_id: "42", full_name: "octocat/project", html_url: "https://github.com/octocat/project",
      default_branch: "main", is_private: true, selected: true,
    }] });
    api.getGitHubProjectOverview.mockResolvedValue(overview);
    api.proposeGitHubIssueActions.mockResolvedValue({
      repository_id: "42", source_id: "9", source_title: "octocat/project · #9 Add indexes",
      suggestions: [{ title: "Add the index", description: null, priority: "normal", due_date: null, source_quote: "Add indexes before launch." }],
    });
    api.getGitHubPullDetail.mockResolvedValue({
      repository_id: "42", number: 10, title: "Add schema index", body: "", state: "open",
      html_url: "https://github.com/octocat/project/pull/10", head_sha: "abc123",
      files: [{ filename: "schema.py", status: "modified", additions: 1, deletions: 0, patch: "+index", html_url: null }],
      checks: [{ name: "tests", status: "completed", conclusion: "success", html_url: null }],
      files_truncated: false, checks_truncated: false,
    });
    api.createActionItem.mockResolvedValue({});
    api.createGitHubIssue.mockResolvedValue({ number: 11, title: "Fix the index", html_url: "https://github.com/octocat/project/issues/11" });
    api.createGitHubIssueComment.mockResolvedValue({ id: "100", html_url: null });
  });

  it("browses a selected project and adds a reviewed issue suggestion to the planner", async () => {
    render(<GitHubProjectPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Load project" }));
    expect(await screen.findByText("Add indexes")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Suggest planner tasks" }));
    expect(await screen.findByText("Add indexes before launch.")).toBeInTheDocument();
    expect(api.createActionItem).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Add to planner" }));
    await waitFor(() => expect(api.createActionItem).toHaveBeenCalledWith({
      title: "Add the index",
      priority: "normal",
      source_type: "github",
      source_id: "9",
      source_repository_id: "42",
      source_quote: "Add indexes before launch.",
    }));
  });

  it("shows changed files and check status for a pull request", async () => {
    render(<GitHubProjectPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Load project" }));
    const user = userEvent.setup();
    const issuesTab = await screen.findByRole("tab", { name: "Issues (1)" });
    issuesTab.focus();
    await user.keyboard("{ArrowRight}");
    const pullsTab = screen.getByRole("tab", { name: "Pull requests (1)" });
    expect(pullsTab).toHaveFocus();
    expect(pullsTab).toHaveAttribute("aria-selected", "true");
    const panel = screen.getByRole("tabpanel", { name: "Pull requests (1)" });
    expect(pullsTab).toHaveAttribute("aria-controls", panel.id);
    fireEvent.click(await screen.findByRole("button", { name: "View diff and checks" }));
    expect(await screen.findByText("schema.py · +1 / −0")).toBeInTheDocument();
    expect(screen.getByText("tests")).toBeInTheDocument();
    expect(screen.getByText("success")).toBeInTheDocument();
  });

  it("requires a separate review and submit action for issue and comment writes", async () => {
    render(<GitHubProjectPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Load project" }));
    await screen.findByText("Add indexes");

    fireEvent.change(screen.getByLabelText("Issue title"), { target: { value: "Fix the index" } });
    fireEvent.change(screen.getByLabelText("Issue body"), { target: { value: "Check the query plan." } });
    fireEvent.click(screen.getByRole("button", { name: "Review issue draft" }));
    expect(await screen.findByText("Will create in octocat/project")).toBeInTheDocument();
    expect(api.createGitHubIssue).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Create issue on GitHub" }));
    await waitFor(() => expect(api.createGitHubIssue).toHaveBeenCalledWith("42", {
      title: "Fix the index", body: "Check the query plan.",
    }));

    fireEvent.click(screen.getByRole("button", { name: "Write comment" }));
    fireEvent.change(screen.getByLabelText("Comment"), { target: { value: "I checked the query plan." } });
    fireEvent.click(screen.getByRole("button", { name: "Review comment" }));
    expect(await screen.findByText("Will post to octocat/project issue #9")).toBeInTheDocument();
    expect(api.createGitHubIssueComment).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Post comment to GitHub" }));
    await waitFor(() => expect(api.createGitHubIssueComment).toHaveBeenCalledWith("42", 9, "I checked the query plan."));
  });

  it("clears reviewed write drafts when changing repositories", async () => {
    api.getGitHubRepositories.mockResolvedValue({ repositories: [
      { repository_id: "42", full_name: "octocat/project", html_url: "https://github.com/octocat/project", default_branch: "main", is_private: true, selected: true },
      { repository_id: "84", full_name: "octocat/other", html_url: "https://github.com/octocat/other", default_branch: "main", is_private: false, selected: true },
    ] });
    render(<GitHubProjectPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Load project" }));
    await screen.findByText("Add indexes");
    fireEvent.change(screen.getByLabelText("Issue title"), { target: { value: "Add a new check" } });
    fireEvent.click(screen.getByRole("button", { name: "Review issue draft" }));
    expect(screen.getByRole("button", { name: "Create issue on GitHub" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("combobox", { name: "Selected repository" }));
    await userEvent.click(await screen.findByRole("option", { name: "octocat/other" }));
    expect(screen.queryByRole("button", { name: "Create issue on GitHub" })).not.toBeInTheDocument();
    expect(api.createGitHubIssue).not.toHaveBeenCalled();
  });
});
