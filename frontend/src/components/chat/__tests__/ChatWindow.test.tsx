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

let mockChatState = {
  messages: [] as { id: string; role: string; content: string; timestamp: string }[],
  streamingContent: "",
  activeToolCalls: [] as { toolName: string; toolInput: string }[],
  isConnected: true,
  isStreaming: false,
  conversationId: undefined as string | undefined,
  connect: mockConnect,
  sendMessage: mockSendMessage,
  clearMessages: mockClearMessages,
  loadConversation: vi.fn(),
};

vi.mock("@/hooks/useChat", () => ({
  useChat: () => mockChatState,
}));

// Mock uploadDocument from api
const mockUploadDocument = vi.fn();
const mockGetAgentCatalog = vi.fn();
vi.mock("@/lib/api", () => ({
  uploadDocument: (...args: unknown[]) => mockUploadDocument(...args),
  getAgentCatalog: (...args: unknown[]) => mockGetAgentCatalog(...args),
}));

// Mock child components to simplify rendering
vi.mock("../MessageBubble", () => ({
  MessageBubble: ({ message }: { message: { content: string } }) => (
    <div data-testid="message-bubble">{message.content}</div>
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
    loadConversation: vi.fn(),
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ChatWindow", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetChatState();
    mockUploadDocument.mockResolvedValue({ id: "uploaded-doc-1" });
    mockGetAgentCatalog.mockResolvedValue({ agents: [] });
  });

  it("renders empty state when no messages", () => {
    render(<ChatWindow />);

    expect(screen.getByText("Start a conversation")).toBeInTheDocument();
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
    await waitFor(() => expect(screen.getByLabelText("Agent model")).toHaveValue("qwen2.5:7b"));
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
    const removeButtons = screen.getAllByRole("button");
    // The remove button is the small X button inside the attachment preview
    const removeBtn = removeButtons.find(
      (btn) => btn.classList.contains("h-5") && btn.classList.contains("w-5")
    );
    expect(removeBtn).toBeTruthy();
    await user.click(removeBtn!);

    // Attachment should be gone
    expect(screen.queryByText("Ready")).not.toBeInTheDocument();
    expect(screen.queryByText("file.pdf")).not.toBeInTheDocument();
  });
});
