import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ChatWindow } from "../ChatWindow";

// ---------------------------------------------------------------------------
// Mock hooks & child components
// ---------------------------------------------------------------------------

const mockSendMessage = vi.fn();
const mockClearMessages = vi.fn();
const mockConnect = vi.fn();
const mockLoadConversation = vi.fn();
const mockGetConversation = vi.fn();
const mockGetConversations = vi.fn();
const mockCreateMemory = vi.fn();
const mockUpdateConversationMemorySettings = vi.fn();
const localStorageValues = new Map<string, string>();

Object.defineProperty(window, "localStorage", {
  configurable: true,
  value: {
    getItem: (key: string) => localStorageValues.get(key) ?? null,
    setItem: (key: string, value: string) => localStorageValues.set(key, value),
    removeItem: (key: string) => localStorageValues.delete(key),
    clear: () => localStorageValues.clear(),
  },
});

let mockChatState = {
  messages: [] as { id: string; clientTurnId?: string; role: string; content: string; timestamp: string }[],
  streamingContent: "",
  activeToolCalls: [] as { toolName: string; toolInput: string }[],
  isConnected: true,
  isStreaming: false,
  conversationId: undefined as string | undefined,
  connect: mockConnect,
  sendMessage: mockSendMessage,
  clearMessages: mockClearMessages,
  loadConversation: mockLoadConversation,
};

vi.mock("@/hooks/useChat", () => ({
  useChat: () => mockChatState,
}));

// Mock uploadDocument from api
const mockUploadDocument = vi.fn();
const mockGetAgentCatalog = vi.fn();
const mockGetRAGContainers = vi.fn();
const mockGetRAGCollections = vi.fn();
vi.mock("@/lib/api", () => ({
  createMemory: (...args: unknown[]) => mockCreateMemory(...args),
  updateConversationMemorySettings: (...args: unknown[]) => mockUpdateConversationMemorySettings(...args),
  uploadDocument: (...args: unknown[]) => mockUploadDocument(...args),
  getAgentCatalog: (...args: unknown[]) => mockGetAgentCatalog(...args),
  getAgentCatalogWithArchived: (...args: unknown[]) => mockGetAgentCatalog(...args),
  getRAGContainers: (...args: unknown[]) => mockGetRAGContainers(...args),
  getRAGCollections: (...args: unknown[]) => mockGetRAGCollections(...args),
  getConversation: (...args: unknown[]) => mockGetConversation(...args),
  getConversations: (...args: unknown[]) => mockGetConversations(...args),
}));

vi.mock("@/components/shared/AuthProvider", () => ({
  useAuth: () => ({ account: { id: "account-alice" } }),
}));

// Mock child components to simplify rendering
vi.mock("../MessageBubble", () => ({
  MessageBubble: ({ message, onRemember }: { message: { id: string; content: string }; onRemember?: (message: unknown) => void }) => (
    <div data-testid="message-bubble">
      {message.content}
      {onRemember && <button onClick={() => onRemember(message)}>Remember this</button>}
    </div>
  ),
}));

vi.mock("../StreamingText", () => ({
  StreamingText: ({ content }: { content: string }) =>
    content ? <div data-testid="streaming-text">{content}</div> : null,
}));

vi.mock("../ToolCallDisplay", () => ({
  ToolCallDisplay: ({ toolCall }: { toolCall: { toolName: string } }) => (
    <div data-testid="tool-call">{toolCall.toolName}</div>
  ),
}));

// ---------------------------------------------------------------------------
// Helper to reset state
// ---------------------------------------------------------------------------

function resetChatState() {
  mockChatState = {
    messages: [],
    streamingContent: "",
    activeToolCalls: [],
    isConnected: true,
    isStreaming: false,
    conversationId: undefined,
    connect: mockConnect,
    sendMessage: mockSendMessage,
    clearMessages: mockClearMessages,
    loadConversation: mockLoadConversation,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ChatWindow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorageValues.clear();
    resetChatState();
    mockUploadDocument.mockResolvedValue({ id: "uploaded-doc-1" });
    mockGetAgentCatalog.mockResolvedValue({ agents: [] });
    mockGetRAGContainers.mockResolvedValue([]);
    mockGetRAGCollections.mockResolvedValue({ collections: [] });
    mockGetConversation.mockResolvedValue({ id: "conversation-1", title: "Saved", messages: [] });
    mockGetConversations.mockResolvedValue({ conversations: [] });
    mockCreateMemory.mockResolvedValue({ id: "saved-memory" });
    mockUpdateConversationMemorySettings.mockImplementation(async (_id: string, settings: { exclude_from_memory: boolean }) => settings);
  });

  it("restores the active account conversation after refresh", async () => {
    window.localStorage.setItem("local-ai-active-conversation:account-alice", "conversation-1");
    mockGetConversation.mockResolvedValue({
      id: "conversation-1",
      title: "Saved",
      messages: [
        {
          id: "message-1",
          role: "user",
          content: "Continue this",
          agent_type: null,
          execution: null,
          created_at: "2026-10-12T10:00:00Z",
          tool_calls: [],
        },
        {
          id: "message-2",
          role: "assistant",
          content: "I checked the files.",
          agent_type: "chat",
          execution: { agent: "chat" },
          created_at: "2026-10-12T10:00:01Z",
          tool_calls: [{
            id: "tool-1",
            tool_name: "read_file",
            tool_input: { path: "notes.md" },
            tool_output: "contents",
            duration_ms: 12,
          }],
        },
      ],
    });

    render(<ChatWindow />);

    await waitFor(() => expect(mockLoadConversation).toHaveBeenCalledWith([
      expect.objectContaining({ id: "message-1", content: "Continue this" }),
      expect.objectContaining({
        id: "message-2",
        agentType: "chat",
        toolCalls: [{
          id: "tool-1",
          toolName: "read_file",
          toolInput: JSON.stringify({ path: "notes.md" }),
          toolOutput: "contents",
          durationMs: 12,
        }],
      }),
    ], "conversation-1"));
  });

  it("previews a chat message and saves it with its client-turn source", async () => {
    mockChatState = {
      ...mockChatState,
      conversationId: "conversation-1",
      messages: [{
        id: "turn-1",
        clientTurnId: "turn-1",
        role: "user",
        content: "My preferred color is cobalt blue.",
        timestamp: "2026-10-12T10:00:00Z",
      }],
    };
    render(<ChatWindow />);
    fireEvent.click(await screen.findByRole("button", { name: "Remember this" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByLabelText("Memory text")).toHaveValue("My preferred color is cobalt blue.");
    fireEvent.click(screen.getByRole("button", { name: "Save memory" }));
    await waitFor(() => expect(mockCreateMemory).toHaveBeenCalledWith({
      kind: "fact",
      content: "My preferred color is cobalt blue.",
      source_conversation_id: "conversation-1",
      source_client_turn_id: "turn-1",
    }));
  });

  it("saves the conversation recall exclusion setting", async () => {
    mockChatState = { ...mockChatState, conversationId: "conversation-1" };
    render(<ChatWindow />);
    fireEvent.click(await screen.findByRole("checkbox", { name: "Exclude this chat from past-chat recall" }));
    await waitFor(() => expect(mockUpdateConversationMemorySettings).toHaveBeenCalledWith(
      "conversation-1",
      { exclude_from_memory: true },
    ));
  });

  it("browses and opens an owned saved conversation", async () => {
    mockGetConversations.mockResolvedValue({
      conversations: [{
        id: "conversation-1",
        title: "Project notes",
        created_at: "2026-10-12T10:00:00Z",
        last_message_at: "2026-10-12T10:01:00Z",
        message_count: 2,
      }],
    });

    render(<ChatWindow />);
    await userEvent.click(screen.getByRole("button", { name: "History" }));
    await userEvent.click(await screen.findByRole("button", { name: /Project notes/ }));

    await waitFor(() => expect(mockLoadConversation).toHaveBeenCalledWith([], "conversation-1"));
    expect(window.localStorage.getItem("local-ai-active-conversation:account-alice")).toBe("conversation-1");
  });

  it("clears the active conversation pointer for a new chat", async () => {
    window.localStorage.setItem("local-ai-active-conversation:account-alice", "conversation-1");
    render(<ChatWindow />);

    await userEvent.click(screen.getByRole("button", { name: "New chat" }));

    expect(mockClearMessages).toHaveBeenCalled();
    expect(window.localStorage.getItem("local-ai-active-conversation:account-alice")).toBeNull();
  });

  it("closes model options when starting a new chat", async () => {
    const user = userEvent.setup();
    render(<ChatWindow />);
    const optionsButton = screen.getByRole("button", { name: "Options" });

    await user.click(optionsButton);
    expect(optionsButton).toHaveAttribute("aria-expanded", "true");
    await user.click(screen.getByRole("button", { name: "New chat" }));

    expect(optionsButton).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Choose an agent profile to configure its model options.")).not.toBeInTheDocument();
  });

  it("renders empty state when no messages", () => {
    render(<ChatWindow />);

    expect(screen.getByText("Start a conversation")).toBeInTheDocument();
  });

  it("fills an editable starter prompt without sending a message", async () => {
    render(<ChatWindow />);
    await userEvent.click(screen.getByRole("button", { name: /Spark an idea/ }));
    const message = screen.getByRole("textbox", { name: "Your message" });
    expect(message).toHaveValue("Help me brainstorm a few creative ideas for ");
    expect(message).toHaveFocus();
    expect(mockSendMessage).not.toHaveBeenCalled();
  });

  it("scrolls messages to the bottom and a new empty chat back to its greeting", () => {
    const { container, rerender } = render(<ChatWindow />);
    const viewport = container.querySelector("[data-radix-scroll-area-viewport]")!;
    Object.defineProperty(viewport, "scrollHeight", { configurable: true, value: 800 });
    mockChatState.messages = [{ id: "1", role: "user", content: "Hello", timestamp: "2024-01-01T00:00:00Z" }];
    rerender(<ChatWindow />);
    expect(viewport.scrollTop).toBe(800);
    mockChatState.messages = [];
    rerender(<ChatWindow />);
    expect(viewport.scrollTop).toBe(0);
  });

  it("loads available profiles into the agent selector", async () => {
    mockGetAgentCatalog.mockResolvedValue({ agents: [
      {
        name: "image_analysis",
        target: "image_analysis",
        description: "Describe uploaded images",
        default_for_target: true,
        inference: { allowed_models: ["qwen2.5vl:7b"], defaults: { model: "qwen2.5vl:7b", temperature: 0.1 }, limits: { temperature: { minimum: 0, maximum: 2 } } },
      },
    ] });
    render(<ChatWindow />);

    await waitFor(() => expect(mockGetAgentCatalog).toHaveBeenCalled());
    expect(screen.getByLabelText("Agent profile").querySelector('option[value="image_analysis"]')).not.toBeNull();
  });

  it("sends profile-specific ticker and inference settings with chat", async () => {
    mockGetAgentCatalog.mockResolvedValue({ agents: [
      {
        name: "stock_research",
        target: "stock_research",
        description: "Research equities",
        default_for_target: true,
        inference: { allowed_models: ["qwen2.5:7b", "llama3.2:3b"], defaults: { model: "qwen2.5:7b", temperature: 0.2 }, limits: { temperature: { minimum: 0, maximum: 2 } } },
      },
    ] });
    render(<ChatWindow />);
    await waitFor(() => expect(screen.getByLabelText("Agent profile").querySelector('option[value="stock_research"]')).not.toBeNull());
    fireEvent.change(screen.getByLabelText("Agent profile"), { target: { value: "stock_research" } });
    fireEvent.click(screen.getByRole("button", { name: "Options" }));
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Agent model" })).toHaveTextContent("qwen2.5:7b"));
    fireEvent.change(screen.getByLabelText("Ticker symbol"), { target: { value: "AAPL" } });
    fireEvent.change(screen.getByPlaceholderText("Type a message... (Shift+Enter for new line)"), {
      target: { value: "Assess current risks." },
    });
    fireEvent.submit(screen.getByPlaceholderText("Type a message... (Shift+Enter for new line)").closest("form")!);

    expect(mockSendMessage).toHaveBeenCalledWith("Assess current risks.", [], {
      agent_name: "stock_research",
      symbol: "AAPL",
      inference: { model: "qwen2.5:7b", temperature: 0.2 },
    });
  });

  it.each([
    { availability: { "qwen2.5:7b": false, "llama3.2:3b": true }, selected: "llama3.2:3b", label: "not installed", blocked: false },
    { availability: { "qwen2.5:7b": false, "llama3.2:3b": false }, selected: "qwen2.5:7b", label: "not installed", blocked: true },
    { availability: { "qwen2.5:7b": null, "llama3.2:3b": null }, selected: "qwen2.5:7b", label: "availability unknown", blocked: false },
  ])("shows actual model availability and chooses $selected ($label)", async ({ availability, selected, label, blocked }) => {
    mockGetRAGCollections.mockResolvedValue({ collections: [{ name: "documents", count: 0 }] });
    mockGetAgentCatalog.mockResolvedValue({ agents: [{
      name: "rag", target: "rag", description: "Answer from evidence", default_for_target: true,
      model_availability: availability,
      inference: { allowed_models: ["qwen2.5:7b", "llama3.2:3b"], defaults: { model: "qwen2.5:7b", temperature: 0.2 }, limits: { temperature: { minimum: 0, maximum: 2 } } },
    }] });
    render(<ChatWindow />);
    await waitFor(() => expect(screen.getByLabelText("Agent profile").querySelector('option[value="rag"]')).not.toBeNull());
    fireEvent.change(screen.getByLabelText("Agent profile"), { target: { value: "rag" } });
    fireEvent.click(screen.getByRole("button", { name: "Options" }));
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Agent model" })).toHaveTextContent(selected));
    fireEvent.keyDown(screen.getByRole("combobox", { name: "Agent model" }), { key: "ArrowDown" });
    expect(screen.getByRole("option", { name: `qwen2.5:7b (${label})` })).toBeInTheDocument();
    const input = screen.getByPlaceholderText("Type a message... (Shift+Enter for new line)");
    fireEvent.change(input, { target: { value: "What is supported?" } });
    fireEvent.submit(input.closest("form")!);
    if (blocked) {
      expect(mockSendMessage).not.toHaveBeenCalled();
      expect(screen.getByText(/Install qwen2.5:7b in Ollama/)).toBeInTheDocument();
    } else {
      expect(mockSendMessage).toHaveBeenCalledWith("What is supported?", [], expect.objectContaining({ inference: { model: selected, temperature: 0.2 } }));
    }
  });

  it("renders messages via MessageBubble", () => {
    mockChatState.messages = [
      { id: "1", role: "user", content: "Hi", timestamp: "2024-01-01T00:00:00Z" },
      { id: "2", role: "assistant", content: "Hello!", timestamp: "2024-01-01T00:00:01Z" },
    ];

    render(<ChatWindow />);

    const bubbles = screen.getAllByTestId("message-bubble");
    expect(bubbles).toHaveLength(2);
    expect(bubbles[0]).toHaveTextContent("Hi");
    expect(bubbles[1]).toHaveTextContent("Hello!");
  });

  it("renders streaming text when content is present", () => {
    mockChatState.streamingContent = "Generating...";

    render(<ChatWindow />);

    expect(screen.getByTestId("streaming-text")).toHaveTextContent("Generating...");
  });

  it("renders active tool calls", () => {
    mockChatState.activeToolCalls = [
      { toolName: "query_db", toolInput: '{"sql":"SELECT 1"}' },
    ];

    render(<ChatWindow />);

    expect(screen.getByTestId("tool-call")).toHaveTextContent("query_db");
  });

  it("submits form and calls sendMessage with empty attachments", async () => {
    const user = userEvent.setup();
    render(<ChatWindow />);

    const textarea = screen.getByPlaceholderText(/Type a message/);
    await user.type(textarea, "Hello AI");

    const form = textarea.closest("form")!;
    fireEvent.submit(form);

    expect(mockSendMessage).toHaveBeenCalledWith("Hello AI", []);
  });

  it("Enter key submits, Shift+Enter does not", async () => {
    const user = userEvent.setup();
    render(<ChatWindow />);

    const textarea = screen.getByPlaceholderText(/Type a message/);
    await user.type(textarea, "Test message");

    // Shift+Enter should NOT submit
    await user.keyboard("{Shift>}{Enter}{/Shift}");
    expect(mockSendMessage).not.toHaveBeenCalled();

    // Enter alone should submit
    await user.keyboard("{Enter}");
    expect(mockSendMessage).toHaveBeenCalledWith("Test message", []);
  });

  it("does not submit empty input with no attachments", async () => {
    render(<ChatWindow />);

    const textarea = screen.getByPlaceholderText(/Type a message/);
    const form = textarea.closest("form")!;
    fireEvent.submit(form);

    expect(mockSendMessage).not.toHaveBeenCalled();
  });

  it("disables input and buttons when streaming", () => {
    mockChatState.isStreaming = true;

    render(<ChatWindow />);

    const textarea = screen.getByPlaceholderText(/Type a message/);
    expect(textarea).toBeDisabled();
  });

  it("new conversation button calls clearMessages", async () => {
    const user = userEvent.setup();
    render(<ChatWindow />);

    const newBtn = screen.getByTitle("New conversation");
    await user.click(newBtn);

    expect(mockClearMessages).toHaveBeenCalled();
  });

  it("shows Disconnected status when not connected", () => {
    mockChatState.isConnected = false;

    render(<ChatWindow />);

    expect(screen.getByText(/Disconnected/)).toBeInTheDocument();
  });

  it("shows Connected when isConnected is true", () => {
    mockChatState.isConnected = true;

    render(<ChatWindow />);

    expect(screen.getByText(/Connected/)).toBeInTheDocument();
  });

  it("calls connect on mount", () => {
    render(<ChatWindow />);
    expect(mockConnect).toHaveBeenCalled();
  });

  it("has an attach file button", () => {
    render(<ChatWindow />);

    const attachBtn = screen.getByTitle("Attach file");
    expect(attachBtn).toBeInTheDocument();
  });

  it("uploads file and shows attachment preview", async () => {
    mockUploadDocument.mockResolvedValue({ id: "doc-abc" });

    render(<ChatWindow />);

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(fileInput).toBeTruthy();

    const file = new File(["hello"], "test.pdf", { type: "application/pdf" });
    fireEvent.change(fileInput, { target: { files: [file] } });

    // Should show uploading state then ready
    await waitFor(() => {
      expect(mockUploadDocument).toHaveBeenCalledWith(file);
    });

    // After upload resolves, "Ready" badge should appear
    await waitFor(() => {
      expect(screen.getByText("Ready")).toBeInTheDocument();
    });
  });

  it("shows error when upload fails", async () => {
    mockUploadDocument.mockRejectedValue(new Error("Server error"));

    render(<ChatWindow />);

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["data"], "doc.pdf", { type: "application/pdf" });
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByText("Upload failed")).toBeInTheDocument();
    });
  });

  it("sends message with uploaded attachment IDs", async () => {
    const user = userEvent.setup();
    mockUploadDocument.mockResolvedValue({ id: "doc-xyz" });

    render(<ChatWindow />);

    // Upload a file first
    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["data"], "image.png", { type: "image/png" });
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByText("Ready")).toBeInTheDocument();
    });

    // Type a message and submit
    const textarea = screen.getByPlaceholderText(/Describe what to do/);
    await user.type(textarea, "Analyze this image");

    const form = textarea.closest("form")!;
    fireEvent.submit(form);

    expect(mockSendMessage).toHaveBeenCalledWith("Analyze this image", ["doc-xyz"]);
  });

  it("can remove an attachment", async () => {
    const user = userEvent.setup();
    mockUploadDocument.mockResolvedValue({ id: "doc-rem" });

    render(<ChatWindow />);

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["data"], "file.pdf", { type: "application/pdf" });
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => {
      expect(screen.getByText("Ready")).toBeInTheDocument();
    });

    // Find and click the remove button (X icon)
    await user.click(screen.getByRole("button", { name: "Remove file.pdf" }));

    // Attachment should be gone
    expect(screen.queryByText("Ready")).not.toBeInTheDocument();
    expect(screen.queryByText("file.pdf")).not.toBeInTheDocument();
  });
});
