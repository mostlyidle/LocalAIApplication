import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";

// ---------------------------------------------------------------------------
// Mock useWebSocket — we test it separately
// ---------------------------------------------------------------------------

const mockWsSend = vi.fn();
const mockConnect = vi.fn();
const mockDisconnect = vi.fn();
let capturedOptions: Record<string, (...args: unknown[]) => void> = {};

vi.mock("../useWebSocket", () => ({
  useWebSocket: (opts: Record<string, (...args: unknown[]) => void>) => {
    capturedOptions = opts;
    return {
      isConnected: true,
      isStreaming: false,
      connect: mockConnect,
      disconnect: mockDisconnect,
      sendMessage: mockWsSend,
    };
  },
}));

// Import after mock setup
import { useChat } from "../useChat";

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useChat", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    capturedOptions = {};
  });

  it("returns initial empty state", () => {
    const { result } = renderHook(() => useChat());

    expect(result.current.messages).toEqual([]);
    expect(result.current.streamingContent).toBe("");
    expect(result.current.activeToolCalls).toEqual([]);
    expect(result.current.conversationId).toBeUndefined();
    expect(result.current.isConnected).toBe(true);
  });

  it("sendMessage adds user message and calls wsSend", () => {
    const { result } = renderHook(() => useChat());

    act(() => {
      result.current.sendMessage("Hello world");
    });

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].role).toBe("user");
    expect(result.current.messages[0].content).toBe("Hello world");
    expect(result.current.messages[0].attachments).toBeUndefined();
    expect(mockWsSend).toHaveBeenCalledWith("Hello world", []);
  });

  it("sendMessage forwards attachments to wsSend", () => {
    const { result } = renderHook(() => useChat());

    act(() => {
      result.current.sendMessage("Analyze this", ["doc-1", "doc-2"]);
    });

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].content).toBe("Analyze this");
    expect(result.current.messages[0].attachments).toEqual(["doc-1", "doc-2"]);
    expect(mockWsSend).toHaveBeenCalledWith("Analyze this", ["doc-1", "doc-2"]);
  });

  it("handleToken appends to streamingContent", () => {
    const { result } = renderHook(() => useChat());

    act(() => {
      capturedOptions.onToken?.("Hello");
    });
    expect(result.current.streamingContent).toBe("Hello");

    act(() => {
      capturedOptions.onToken?.(" world");
    });
    expect(result.current.streamingContent).toBe("Hello world");
  });

  it("handleToolCall adds to activeToolCalls", () => {
    const { result } = renderHook(() => useChat());

    act(() => {
      capturedOptions.onToolCall?.("query_db", { sql: "SELECT 1" });
    });

    expect(result.current.activeToolCalls).toHaveLength(1);
    expect(result.current.activeToolCalls[0].toolName).toBe("query_db");
  });

  it("handleToolResult updates matching tool call", () => {
    const { result } = renderHook(() => useChat());

    act(() => {
      capturedOptions.onToolCall?.("query_db", { sql: "SELECT 1" });
    });

    act(() => {
      capturedOptions.onToolResult?.("query_db", "1 row returned");
    });

    expect(result.current.activeToolCalls[0].toolOutput).toBe("1 row returned");
  });

  it("handleDone creates assistant message from streamed content", () => {
    const { result } = renderHook(() => useChat());

    // Stream some content first
    act(() => {
      capturedOptions.onToken?.("Result: 42");
    });
    expect(result.current.streamingContent).toBe("Result: 42");

    act(() => {
      capturedOptions.onDone?.({ agents_invoked: ["sql_agent"], conversation_id: "conv-1" });
    });

    // Streaming content should be cleared
    expect(result.current.streamingContent).toBe("");
    // Assistant message should be added
    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].role).toBe("assistant");
    expect(result.current.messages[0].content).toBe("Result: 42");
    expect(result.current.messages[0].agentType).toBe("sql_agent");
    // Conversation ID should be set
    expect(result.current.conversationId).toBe("conv-1");
  });

  it("handleDone does not add empty assistant message", () => {
    const { result } = renderHook(() => useChat());

    act(() => {
      capturedOptions.onDone?.({});
    });

    expect(result.current.messages).toHaveLength(0);
  });

  it("handleError creates error assistant message", () => {
    const { result } = renderHook(() => useChat());

    act(() => {
      capturedOptions.onError?.("Connection timed out");
    });

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.messages[0].role).toBe("assistant");
    expect(result.current.messages[0].content).toBe("Error: Connection timed out");
    expect(result.current.streamingContent).toBe("");
  });

  it("clearMessages resets all state", () => {
    const { result } = renderHook(() => useChat());

    // Build up some state
    act(() => {
      result.current.sendMessage("Hi");
    });
    act(() => {
      capturedOptions.onToken?.("Hello");
    });

    expect(result.current.messages).toHaveLength(1);
    expect(result.current.streamingContent).toBe("Hello");

    act(() => {
      result.current.clearMessages();
    });

    expect(result.current.messages).toEqual([]);
    expect(result.current.streamingContent).toBe("");
    expect(result.current.activeToolCalls).toEqual([]);
    expect(result.current.conversationId).toBeUndefined();
  });

  it("loadConversation sets messages and conversationId", () => {
    const { result } = renderHook(() => useChat());

    const msgs = [
      { id: "1", role: "user" as const, content: "hi", timestamp: "2024-01-01T00:00:00Z" },
      { id: "2", role: "assistant" as const, content: "hello", timestamp: "2024-01-01T00:00:01Z" },
    ];

    act(() => {
      result.current.loadConversation(msgs, "conv-123");
    });

    expect(result.current.messages).toEqual(msgs);
    expect(result.current.conversationId).toBe("conv-123");
  });

  it("sendMessage resets streamingContent and activeToolCalls", () => {
    const { result } = renderHook(() => useChat());

    // Simulate some streaming state
    act(() => {
      capturedOptions.onToken?.("partial");
    });
    act(() => {
      capturedOptions.onToolCall?.("tool1", {});
    });

    expect(result.current.streamingContent).toBe("partial");
    expect(result.current.activeToolCalls).toHaveLength(1);

    act(() => {
      result.current.sendMessage("new message");
    });

    expect(result.current.streamingContent).toBe("");
    expect(result.current.activeToolCalls).toEqual([]);
  });
});
