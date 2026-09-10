import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useWebSocket } from "../useWebSocket";

// ---------------------------------------------------------------------------
// Mock WebSocket
// ---------------------------------------------------------------------------

class MockWebSocket {
  static OPEN = 1;
  static CLOSED = 3;
  static instances: MockWebSocket[] = [];

  readyState = MockWebSocket.OPEN;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  send = vi.fn();
  close = vi.fn(() => {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.();
  });

  constructor(public url: string) {
    MockWebSocket.instances.push(this);
    // Simulate async open
    setTimeout(() => {
      if (this.readyState !== MockWebSocket.CLOSED) {
        this.onopen?.();
      }
    }, 0);
  }
}

// Apply to global before each test
beforeEach(() => {
  MockWebSocket.instances = [];
  vi.useFakeTimers();
  (globalThis as unknown as Record<string, unknown>).WebSocket = MockWebSocket as unknown as typeof WebSocket;
  // Also put OPEN/CLOSED on the constructor for the readyState checks
  (globalThis as unknown as Record<string, unknown>).WebSocket = Object.assign(MockWebSocket, {
    CONNECTING: 0,
    OPEN: 1,
    CLOSING: 2,
    CLOSED: 3,
  }) as unknown as typeof WebSocket;
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useWebSocket", () => {
  it("sends the conversation ID and shows backend content errors", async () => {
    const onError = vi.fn();
    const { result } = renderHook(() => useWebSocket({ onError }));
    act(() => result.current.connect());
    await act(async () => { vi.advanceTimersByTime(1); });
    act(() => result.current.sendMessage("Follow up", [], "conversation-1"));
    const ws = MockWebSocket.instances[0];
    expect(JSON.parse(ws.send.mock.calls[0][0]).conversation_id).toBe("conversation-1");
    act(() => ws.onmessage?.({ data: JSON.stringify({ type: "error", content: "Backend unavailable" }) }));
    expect(onError).toHaveBeenCalledWith("Backend unavailable");
    expect(result.current.isStreaming).toBe(false);
  });

  it("reports a queued message that cannot connect instead of silently dropping it", async () => {
    const onError = vi.fn();
    const { result, unmount } = renderHook(() => useWebSocket({ onError }));
    act(() => {
      result.current.sendMessage("Hello");
      MockWebSocket.instances[0].readyState = 0;
      MockWebSocket.instances[0].onopen = null;
    });
    expect(result.current.isStreaming).toBe(true);
    await act(async () => { vi.advanceTimersByTime(5000); });
    expect(onError).toHaveBeenCalledWith(expect.stringContaining("Could not connect"));
    expect(result.current.isStreaming).toBe(false);
    expect(MockWebSocket.instances[0].send).not.toHaveBeenCalled();
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("returns initial disconnected state", () => {
    const { result } = renderHook(() => useWebSocket());

    expect(result.current.isConnected).toBe(false);
    expect(result.current.isStreaming).toBe(false);
  });

  it("connect() creates WebSocket and sets isConnected on open", async () => {
    const { result } = renderHook(() => useWebSocket());

    act(() => {
      result.current.connect();
    });

    expect(MockWebSocket.instances).toHaveLength(1);

    // Fire the setTimeout that triggers onopen
    await act(async () => {
      vi.advanceTimersByTime(1);
    });

    expect(result.current.isConnected).toBe(true);
  });

  it("connect() is idempotent when already open", async () => {
    const { result } = renderHook(() => useWebSocket());

    act(() => {
      result.current.connect();
    });
    await act(async () => {
      vi.advanceTimersByTime(1);
    });

    // Call connect again — should not create a second WS
    act(() => {
      result.current.connect();
    });

    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it("disconnect() closes WebSocket and sets isConnected false", async () => {
    const { result } = renderHook(() => useWebSocket());

    act(() => {
      result.current.connect();
    });
    await act(async () => {
      vi.advanceTimersByTime(1);
    });
    expect(result.current.isConnected).toBe(true);

    act(() => {
      result.current.disconnect();
    });

    expect(result.current.isConnected).toBe(false);
    expect(MockWebSocket.instances[0].close).toHaveBeenCalled();
  });

  it("sendMessage sends JSON when connected", async () => {
    const { result } = renderHook(() => useWebSocket());

    act(() => {
      result.current.connect();
    });
    await act(async () => {
      vi.advanceTimersByTime(1);
    });

    act(() => {
      result.current.sendMessage("hello");
    });

    const ws = MockWebSocket.instances[0];
    expect(ws.send).toHaveBeenCalledWith(
      JSON.stringify({ type: "message", content: "hello", attachments: [] }),
    );
    expect(result.current.isStreaming).toBe(true);
  });

  it("sendMessage reconnects and sends when not connected", async () => {
    const { result } = renderHook(() => useWebSocket());

    // Send without connecting first
    act(() => {
      result.current.sendMessage("hi");
    });

    // A new WS should be created
    expect(MockWebSocket.instances).toHaveLength(1);

    // Simulate open
    await act(async () => {
      vi.advanceTimersByTime(1);
    });

    // The interval (50ms) should detect open and send
    await act(async () => {
      vi.advanceTimersByTime(50);
    });

    const ws = MockWebSocket.instances[0];
    expect(ws.send).toHaveBeenCalledWith(
      JSON.stringify({ type: "message", content: "hi", attachments: [] }),
    );
  });

  it("dispatches onToken callback", async () => {
    const onToken = vi.fn();
    const { result } = renderHook(() => useWebSocket({ onToken }));

    act(() => {
      result.current.connect();
    });
    await act(async () => {
      vi.advanceTimersByTime(1);
    });

    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.onmessage?.({ data: JSON.stringify({ type: "token", content: "Hello" }) });
    });

    expect(onToken).toHaveBeenCalledWith("Hello");
  });

  it("dispatches onToolCall callback", async () => {
    const onToolCall = vi.fn();
    const { result } = renderHook(() => useWebSocket({ onToolCall }));

    act(() => {
      result.current.connect();
    });
    await act(async () => {
      vi.advanceTimersByTime(1);
    });

    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.onmessage?.({
        data: JSON.stringify({ type: "tool_call", tool: "calc", input: { x: 1 } }),
      });
    });

    expect(onToolCall).toHaveBeenCalledWith("calc", { x: 1 });
  });

  it("dispatches onToolResult callback", async () => {
    const onToolResult = vi.fn();
    const { result } = renderHook(() => useWebSocket({ onToolResult }));

    act(() => {
      result.current.connect();
    });
    await act(async () => {
      vi.advanceTimersByTime(1);
    });

    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.onmessage?.({
        data: JSON.stringify({ type: "tool_result", tool: "calc", output: "42" }),
      });
    });

    expect(onToolResult).toHaveBeenCalledWith("calc", "42");
  });

  it("dispatches onDone callback and sets isStreaming false", async () => {
    const onDone = vi.fn();
    const { result } = renderHook(() => useWebSocket({ onDone }));

    act(() => {
      result.current.connect();
    });
    await act(async () => {
      vi.advanceTimersByTime(1);
    });

    // Manually set streaming to true
    act(() => {
      result.current.sendMessage("test");
    });
    expect(result.current.isStreaming).toBe(true);

    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.onmessage?.({
        data: JSON.stringify({ type: "done", metadata: { tokens_used: 100 } }),
      });
    });

    expect(onDone).toHaveBeenCalledWith({ tokens_used: 100 });
    expect(result.current.isStreaming).toBe(false);
  });

  it("dispatches onError callback and sets isStreaming false", async () => {
    const onError = vi.fn();
    const { result } = renderHook(() => useWebSocket({ onError }));

    act(() => {
      result.current.connect();
    });
    await act(async () => {
      vi.advanceTimersByTime(1);
    });

    act(() => {
      result.current.sendMessage("test");
    });

    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.onmessage?.({
        data: JSON.stringify({ type: "error", error: "LLM timeout" }),
      });
    });

    expect(onError).toHaveBeenCalledWith("LLM timeout");
    expect(result.current.isStreaming).toBe(false);
  });

  it("handles non-JSON message gracefully", async () => {
    const onToken = vi.fn();
    const { result } = renderHook(() => useWebSocket({ onToken }));

    act(() => {
      result.current.connect();
    });
    await act(async () => {
      vi.advanceTimersByTime(1);
    });

    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.onmessage?.({ data: "not-json" });
    });

    // Should not throw, onToken not called
    expect(onToken).not.toHaveBeenCalled();
  });

  it("sets isConnected false and isStreaming false on close", async () => {
    const { result } = renderHook(() => useWebSocket());

    act(() => {
      result.current.connect();
    });
    await act(async () => {
      vi.advanceTimersByTime(1);
    });
    expect(result.current.isConnected).toBe(true);

    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.onclose?.();
    });

    expect(result.current.isConnected).toBe(false);
    expect(result.current.isStreaming).toBe(false);
  });

  it("sets isConnected false on error event", async () => {
    const { result } = renderHook(() => useWebSocket());

    act(() => {
      result.current.connect();
    });
    await act(async () => {
      vi.advanceTimersByTime(1);
    });

    const ws = MockWebSocket.instances[0];
    act(() => {
      ws.onerror?.();
    });

    expect(result.current.isConnected).toBe(false);
    expect(result.current.isStreaming).toBe(false);
  });

  it("cleans up WebSocket on unmount", async () => {
    const { result, unmount } = renderHook(() => useWebSocket());

    act(() => {
      result.current.connect();
    });
    await act(async () => {
      vi.advanceTimersByTime(1);
    });

    const ws = MockWebSocket.instances[0];
    unmount();

    expect(ws.close).toHaveBeenCalled();
  });

  // --- Auto-reconnect tests ---

  it("schedules reconnect after unexpected close", async () => {
    const { result } = renderHook(() => useWebSocket());

    act(() => {
      result.current.connect();
    });
    await act(async () => {
      vi.advanceTimersByTime(1);
    });
    expect(result.current.isConnected).toBe(true);
    expect(MockWebSocket.instances).toHaveLength(1);

    // Simulate unexpected close (server dropped)
    act(() => {
      const ws = MockWebSocket.instances[0];
      ws.readyState = MockWebSocket.CLOSED;
      ws.onclose?.();
    });
    expect(result.current.isConnected).toBe(false);

    // Advance past first reconnect delay (1000ms base)
    await act(async () => {
      vi.advanceTimersByTime(1100);
    });

    // A second WebSocket should have been created
    expect(MockWebSocket.instances).toHaveLength(2);
  });

  it("uses exponential backoff for reconnection", async () => {
    const { result } = renderHook(() => useWebSocket({ maxReconnectAttempts: 3 }));

    act(() => {
      result.current.connect();
    });
    await act(async () => {
      vi.advanceTimersByTime(1);
    });

    // First close => reconnect after 1000ms (attempt 0, delay = 1000 * 2^0 = 1000)
    act(() => {
      const ws = MockWebSocket.instances[0];
      ws.readyState = MockWebSocket.CLOSED;
      ws.onclose?.();
    });

    // At 500ms, no reconnect yet
    await act(async () => {
      vi.advanceTimersByTime(500);
    });
    expect(MockWebSocket.instances).toHaveLength(1);

    // At 1000ms, first reconnect fires
    await act(async () => {
      vi.advanceTimersByTime(500);
    });
    expect(MockWebSocket.instances).toHaveLength(2);

    // Close the second WS immediately (before its onopen timeout fires),
    // so reconnectAttemptRef stays at 1. Delay = 1000 * 2^1 = 2000ms.
    act(() => {
      const ws = MockWebSocket.instances[1];
      ws.readyState = MockWebSocket.CLOSED;
      ws.onclose?.();
    });

    // At 1500ms into the 2000ms delay, no reconnect yet
    await act(async () => {
      vi.advanceTimersByTime(1500);
    });
    expect(MockWebSocket.instances).toHaveLength(2);

    // At 2000ms, second reconnect fires
    await act(async () => {
      vi.advanceTimersByTime(500);
    });
    expect(MockWebSocket.instances).toHaveLength(3);
  });

  it("stops reconnecting after maxReconnectAttempts", async () => {
    const { result } = renderHook(() => useWebSocket({ maxReconnectAttempts: 1 }));

    act(() => {
      result.current.connect();
    });
    await act(async () => {
      vi.advanceTimersByTime(1);
    });

    // First close => reconnect after 1000ms (attempt 0 => increments to 1)
    act(() => {
      const ws = MockWebSocket.instances[0];
      ws.readyState = MockWebSocket.CLOSED;
      ws.onclose?.();
    });

    await act(async () => {
      vi.advanceTimersByTime(1000);
    });
    expect(MockWebSocket.instances).toHaveLength(2);

    // Second close BEFORE onopen fires. reconnectAttemptRef is now 1 (>= maxAttempts).
    // scheduleReconnect should bail out.
    act(() => {
      const ws = MockWebSocket.instances[1];
      ws.readyState = MockWebSocket.CLOSED;
      ws.onclose?.();
    });

    await act(async () => {
      vi.advanceTimersByTime(10000);
    });
    // No third WebSocket
    expect(MockWebSocket.instances).toHaveLength(2);
  });

  it("does not reconnect on intentional disconnect", async () => {
    const { result } = renderHook(() => useWebSocket());

    act(() => {
      result.current.connect();
    });
    await act(async () => {
      vi.advanceTimersByTime(1);
    });

    // Intentional disconnect
    act(() => {
      result.current.disconnect();
    });

    // Wait well past reconnect delay
    await act(async () => {
      vi.advanceTimersByTime(5000);
    });

    // Should NOT have created a second WebSocket
    expect(MockWebSocket.instances).toHaveLength(1);
  });

  it("resets reconnect attempts on successful connection", async () => {
    const { result } = renderHook(() => useWebSocket({ maxReconnectAttempts: 2 }));

    act(() => {
      result.current.connect();
    });
    await act(async () => {
      vi.advanceTimersByTime(1);
    });

    // First close => uses attempt #1
    act(() => {
      const ws = MockWebSocket.instances[0];
      ws.readyState = MockWebSocket.CLOSED;
      ws.onclose?.();
    });

    await act(async () => {
      vi.advanceTimersByTime(1100);
    });
    expect(MockWebSocket.instances).toHaveLength(2);

    // Simulate successful open on the reconnected socket
    await act(async () => {
      vi.advanceTimersByTime(1);
    });
    expect(result.current.isConnected).toBe(true);

    // Close again => attempt counter should have been reset, so we can reconnect again
    act(() => {
      const ws = MockWebSocket.instances[1];
      ws.readyState = MockWebSocket.CLOSED;
      ws.onclose?.();
    });

    await act(async () => {
      vi.advanceTimersByTime(1100);
    });
    expect(MockWebSocket.instances).toHaveLength(3);
  });
});
