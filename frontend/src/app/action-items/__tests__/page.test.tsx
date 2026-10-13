import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const api = vi.hoisted(() => ({
  createActionItem: vi.fn(),
  deleteActionItem: vi.fn(),
  getActionItems: vi.fn(),
  getConversations: vi.fn(),
  getDocuments: vi.fn(),
  getMeetings: vi.fn(),
  proposeActionItems: vi.fn(),
  updateActionItem: vi.fn(),
}));

vi.mock("@/lib/api", () => api);

import ActionItemsPage from "../page";

const item = {
  id: "planner-task-1",
  title: "Send meeting notes",
  description: "Share with the team",
  status: "next" as const,
  priority: "high" as const,
  due_date: "2026-10-20",
  source_type: null,
  source_id: null,
  revision: 1,
  created_at: "2026-10-12T12:00:00Z",
  updated_at: "2026-10-12T12:00:00Z",
};

describe("ActionItemsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    api.getActionItems.mockResolvedValue({ items: [], total: 0 });
    api.getConversations.mockResolvedValue({ conversations: [] });
    api.getDocuments.mockResolvedValue({ documents: [] });
    api.getMeetings.mockResolvedValue([]);
    api.proposeActionItems.mockResolvedValue({ source_type: "chat", source_id: "chat-1", source_title: "A chat", suggestions: [] });
    api.createActionItem.mockResolvedValue(item);
    api.updateActionItem.mockResolvedValue({ ...item, status: "done", revision: 2 });
  });

  it("creates and lists an action item", async () => {
    api.getActionItems
      .mockResolvedValueOnce({ items: [], total: 0 })
      .mockResolvedValueOnce({ items: [item], total: 1 });
    render(<ActionItemsPage />);
    fireEvent.change(screen.getByLabelText("Title"), { target: { value: item.title } });
    fireEvent.change(screen.getByLabelText("Details"), { target: { value: item.description } });
    fireEvent.click(screen.getByRole("button", { name: "Add to planner" }));

    await waitFor(() => expect(api.createActionItem).toHaveBeenCalledWith({
      title: item.title,
      description: item.description,
      priority: "normal",
    }));
    expect(await screen.findByText(item.title)).toBeTruthy();
  });

  it("updates task status", async () => {
    api.getActionItems.mockResolvedValueOnce({ items: [item], total: 1 });
    render(<ActionItemsPage />);

    fireEvent.change(await screen.findByLabelText(`Status for ${item.title}`), {
      target: { value: "done" },
    });
    await waitFor(() => expect(api.updateActionItem).toHaveBeenCalledWith(item.id, {
      revision: 1,
      status: "done",
    }));

  });

  it("shows a readable error when the planner fails to load", async () => {
    api.getActionItems.mockRejectedValueOnce(new Error("Network unavailable"));
    render(<ActionItemsPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Network unavailable");
  });

  it("accepts a source-quoted suggestion only after review", async () => {
    api.getConversations.mockResolvedValue({ conversations: [{ id: "chat-1", title: "A chat" }] });
    api.proposeActionItems.mockResolvedValue({
      source_type: "chat",
      source_id: "chat-1",
      source_title: "A chat",
      suggestions: [{
        title: "Send the update",
        description: "Share progress",
        priority: "normal",
        due_date: null,
        source_quote: "I will send the update tomorrow.",
      }, {
        title: "Prepare the slides",
        description: null,
        priority: "normal",
        due_date: null,
        source_quote: "We need to prepare slides.",
      }],
    });
    render(<ActionItemsPage />);

    await screen.findByRole("option", { name: "A chat" });
    fireEvent.change(screen.getByLabelText("Source"), { target: { value: "chat-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Suggest next steps" }));
    expect(await screen.findByText(/I will send the update tomorrow\./)).toBeTruthy();
    expect(api.createActionItem).not.toHaveBeenCalled();
    let finishCreate!: (created: typeof item) => void;
    api.createActionItem.mockReturnValueOnce(new Promise((resolve) => { finishCreate = resolve; }));
    const acceptButtons = screen.getAllByRole("button", { name: "Accept" });
    fireEvent.click(acceptButtons[0]);
    await waitFor(() => {
      expect(screen.getAllByRole("button", { name: "Accept" }).every((button) => (button as HTMLButtonElement).disabled)).toBe(true);
      expect(screen.getAllByRole("button", { name: "Ignore" }).every((button) => (button as HTMLButtonElement).disabled)).toBe(true);
    });
    fireEvent.click(acceptButtons[0]);
    expect(api.createActionItem).toHaveBeenCalledTimes(1);
    finishCreate(item);
    await waitFor(() => expect(api.createActionItem).toHaveBeenCalledWith({
      title: "Send the update",
      description: "Share progress",
      priority: "normal",
      source_type: "chat",
      source_id: "chat-1",
      source_quote: "I will send the update tomorrow.",
    }));
    expect(await screen.findByText(/We need to prepare slides\./)).toBeTruthy();
  });
});
