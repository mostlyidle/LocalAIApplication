import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("@/lib/api", () => ({
  getMemories: vi.fn(),
  getMemorySettings: vi.fn(),
  createMemory: vi.fn(),
  updateMemory: vi.fn(),
  deleteMemory: vi.fn(),
  updateMemorySettings: vi.fn(),
  deleteAllMemories: vi.fn(),
}));

import * as api from "@/lib/api";
import MemoryPage from "../page";

const savedMemory = {
  id: "m1",
  kind: "preference" as const,
  content: "Concise answers",
  project_scope: null,
  source_conversation_id: null,
  source_message_id: null,
  origin_agent: null,
  created_at: "2026-10-12T00:00:00Z",
  updated_at: "2026-10-12T00:00:00Z",
  expires_at: null,
  revision: 1,
};

describe("MemoryPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getMemories).mockResolvedValue({ memories: [savedMemory], total: 1, limit: 100, offset: 0 });
    vi.mocked(api.getMemorySettings).mockResolvedValue({ memory_enabled: false, past_chat_recall_enabled: false });
    vi.mocked(api.updateMemorySettings).mockImplementation(async (settings) => ({
      memory_enabled: settings.memory_enabled ?? false,
      past_chat_recall_enabled: settings.past_chat_recall_enabled ?? false,
    }));
    vi.mocked(api.createMemory).mockResolvedValue(savedMemory);
    vi.mocked(api.updateMemory).mockResolvedValue({ ...savedMemory, content: "Updated preference", revision: 2 });
    vi.mocked(api.deleteMemory).mockResolvedValue(undefined);
    vi.mocked(api.deleteAllMemories).mockResolvedValue({ deleted_count: 1, memory_epoch: 1, past_chat_recall_enabled: false });
  });

  it("loads saved memories and keeps both memory features off by default", async () => {
    render(<MemoryPage />);
    expect(await screen.findByText("Concise answers")).toBeDefined();
    expect(screen.getByRole("checkbox", { name: "Use saved memories" }).hasAttribute("checked")).toBe(false);
    expect(screen.getByRole("checkbox", { name: "Search past conversations" }).hasAttribute("checked")).toBe(false);
  });

  it("creates a user-approved memory from the exact submitted text", async () => {
    render(<MemoryPage />);
    fireEvent.change(await screen.findByLabelText("Memory"), { target: { value: "I prefer short replies." } });
    fireEvent.click(screen.getByRole("button", { name: "Save memory" }));
    await waitFor(() => expect(api.createMemory).toHaveBeenCalledWith({ content: "I prefer short replies.", kind: "fact" }));
  });

  it("uses revision checks when editing and deleting", async () => {
    const confirm = vi.fn().mockReturnValue(true);
    vi.stubGlobal("confirm", confirm);
    render(<MemoryPage />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
    const editor = screen.getByLabelText("Memory");
    fireEvent.change(editor, { target: { value: "I prefer concise answers." } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => expect(api.updateMemory).toHaveBeenCalledWith("m1", {
      revision: 1,
      content: "I prefer concise answers.",
      kind: "preference",
      project_scope: null,
    }));
    fireEvent.click(await screen.findByRole("button", { name: "Delete memory: Concise answers" }));
    await waitFor(() => expect(api.deleteMemory).toHaveBeenCalledWith("m1", 1));
    vi.unstubAllGlobals();
  });

  it("updates the account memory setting independently", async () => {
    render(<MemoryPage />);
    fireEvent.click(await screen.findByRole("checkbox", { name: "Use saved memories" }));
    await waitFor(() => expect(api.updateMemorySettings).toHaveBeenCalledWith({ memory_enabled: true }));
    expect(api.updateMemorySettings).not.toHaveBeenCalledWith({ past_chat_recall_enabled: true });
  });
});
