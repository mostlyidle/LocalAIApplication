"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { WS_CHAT } from "@/lib/constants";
import type { StreamEvent } from "@/types/chat";
import type { ChatTaskOptions } from "@/types/chat";

interface UseWebSocketOptions {
  onToken?: (token: string) => void;
  onToolCall?: (tool: string, input: Record<string, unknown>) => void;
  onToolResult?: (tool: string, output: string) => void;
  onDone?: (metadata: Record<string, unknown>) => void;
  onError?: (error: string) => void;
  /** Maximum number of automatic reconnection attempts (default: 5) */
  maxReconnectAttempts?: number;
}

const BASE_RECONNECT_DELAY_MS = 1000;
const MAX_RECONNECT_DELAY_MS = 30000;

export function useWebSocket(options: UseWebSocketOptions = {}) {
  const wsRef = useRef<WebSocket | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const optionsRef = useRef(options);
  optionsRef.current = options;
  const reconnectAttemptRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const sendTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pendingMessageRef = useRef<string | null>(null);
  const streamingRef = useRef(false);
  const intentionalCloseRef = useRef(false);
  const mountedRef = useRef(true);

  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimerRef.current !== null) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }, []);

  const clearPendingMessage = useCallback(() => {
    if (sendTimeoutRef.current !== null) {
      clearTimeout(sendTimeoutRef.current);
      sendTimeoutRef.current = null;
    }
    pendingMessageRef.current = null;
  }, []);

  const connect = useCallback(function connectSocket() {
    if (wsRef.current?.readyState === WebSocket.OPEN ||
        wsRef.current?.readyState === WebSocket.CONNECTING) return;
    intentionalCloseRef.current = false;
    clearReconnectTimer();

    const ws = new WebSocket(WS_CHAT);
    wsRef.current = ws;

    ws.onopen = () => {
      if (!mountedRef.current || wsRef.current !== ws) return;
      setIsConnected(true);
      reconnectAttemptRef.current = 0;
      if (pendingMessageRef.current !== null) {
        ws.send(pendingMessageRef.current);
        clearPendingMessage();
      }
    };

    ws.onmessage = (event) => {
      if (!mountedRef.current || wsRef.current !== ws) return;
      let data: StreamEvent;
      try {
        data = JSON.parse(event.data);
      } catch {
        return;
      }
      switch (data.type) {
        case "token":
          optionsRef.current.onToken?.(data.content ?? "");
          break;
        case "tool_call":
          optionsRef.current.onToolCall?.(data.tool ?? "", data.input ?? {});
          break;
        case "tool_result":
          optionsRef.current.onToolResult?.(data.tool ?? "", data.output ?? "");
          break;
        case "done":
          streamingRef.current = false;
          setIsStreaming(false);
          optionsRef.current.onDone?.(data.metadata ?? {});
          break;
        case "error":
          streamingRef.current = false;
          setIsStreaming(false);
          optionsRef.current.onError?.(data.content ?? data.error ?? "Unknown error");
          break;
      }
    };

    ws.onclose = () => {
      if (!mountedRef.current || wsRef.current !== ws) return;
      wsRef.current = null;
      setIsConnected(false);
      if (streamingRef.current && pendingMessageRef.current === null) {
        streamingRef.current = false;
        setIsStreaming(false);
        optionsRef.current.onError?.("Connection lost before the response completed. Please retry.");
      }
      if (intentionalCloseRef.current ||
          reconnectAttemptRef.current >= (optionsRef.current.maxReconnectAttempts ?? 5)) return;
      const delay = Math.min(
        BASE_RECONNECT_DELAY_MS * Math.pow(2, reconnectAttemptRef.current++),
        MAX_RECONNECT_DELAY_MS,
      );
      clearReconnectTimer();
      reconnectTimerRef.current = setTimeout(() => {
        if (mountedRef.current && !intentionalCloseRef.current) connectSocket();
      }, delay);
    };

    ws.onerror = () => {
      if (mountedRef.current && wsRef.current === ws) setIsConnected(false);
      // onclose handles failed sends and reconnects.
    };
  }, [clearReconnectTimer, clearPendingMessage]);

  const disconnect = useCallback(() => {
    intentionalCloseRef.current = true;
    clearReconnectTimer();
    clearPendingMessage();
    streamingRef.current = false;
    const ws = wsRef.current;
    wsRef.current = null;
    ws?.close();
    setIsConnected(false);
    setIsStreaming(false);
  }, [clearReconnectTimer, clearPendingMessage]);

  const sendMessage = useCallback(
    (
      content: string,
      attachments: string[] = [],
      conversationId?: string,
      taskOptions?: ChatTaskOptions,
      clientTurnId?: string,
    ) => {
      const payload = JSON.stringify({
        type: "message", content, attachments, conversation_id: conversationId,
        client_turn_id: clientTurnId, ...taskOptions,
      });
      if (streamingRef.current) return;
      streamingRef.current = true;
      setIsStreaming(true);
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(payload);
        return;
      }
      pendingMessageRef.current = payload;
      sendTimeoutRef.current = setTimeout(() => {
        const ws = wsRef.current;
        if (ws?.readyState === WebSocket.CONNECTING) {
          wsRef.current = null;
          ws.close();
        }
        clearPendingMessage();
        streamingRef.current = false;
        setIsStreaming(false);
        optionsRef.current.onError?.("Could not connect to the backend. Please retry.");
      }, 5000);
      connect();
    },
    [connect, clearPendingMessage],
  );

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      clearReconnectTimer();
      clearPendingMessage();
      const ws = wsRef.current;
      wsRef.current = null;
      ws?.close();
    };
  }, [clearReconnectTimer, clearPendingMessage]);

  return { isConnected, isStreaming, connect, disconnect, sendMessage };
}
