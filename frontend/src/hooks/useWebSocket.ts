"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { WS_CHAT } from "@/lib/constants";
import type { StreamEvent } from "@/types/chat";

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
  const intentionalCloseRef = useRef(false);
  const maxAttempts = options.maxReconnectAttempts ?? 5;
  const mountedRef = useRef(true);
  const sendQueueRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimerRef.current !== null) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }, []);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    // Clean up any pending reconnect
    clearReconnectTimer();

    const ws = new WebSocket(WS_CHAT);
    wsRef.current = ws;

    ws.onopen = () => {
      if (!mountedRef.current) return;
      setIsConnected(true);
      reconnectAttemptRef.current = 0;
    };

    ws.onmessage = (event) => {
      try {
        const data: StreamEvent = JSON.parse(event.data);
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
            optionsRef.current.onDone?.(data.metadata ?? {});
            setIsStreaming(false);
            break;
          case "error":
            optionsRef.current.onError?.(data.error ?? "Unknown error");
            setIsStreaming(false);
            break;
        }
      } catch {
        // Non-JSON message, ignore
      }
    };

    ws.onclose = () => {
      if (!mountedRef.current) return;
      setIsConnected(false);
      setIsStreaming(false);
      scheduleReconnect();
    };

    ws.onerror = () => {
      if (!mountedRef.current) return;
      setIsConnected(false);
      setIsStreaming(false);
      // onclose will fire after onerror, which handles reconnect
    };
  }, [clearReconnectTimer]); // eslint-disable-line react-hooks/exhaustive-deps

  const scheduleReconnect = useCallback(() => {
    if (intentionalCloseRef.current) return;
    if (!mountedRef.current) return;
    if (reconnectAttemptRef.current >= maxAttempts) return;

    const attempt = reconnectAttemptRef.current;
    const delay = Math.min(
      BASE_RECONNECT_DELAY_MS * Math.pow(2, attempt),
      MAX_RECONNECT_DELAY_MS,
    );
    reconnectAttemptRef.current = attempt + 1;

    clearReconnectTimer();
    reconnectTimerRef.current = setTimeout(() => {
      if (mountedRef.current && !intentionalCloseRef.current) {
        connect();
      }
    }, delay);
  }, [maxAttempts, clearReconnectTimer, connect]);

  const disconnect = useCallback(() => {
    intentionalCloseRef.current = true;
    clearReconnectTimer();
    if (sendQueueRef.current !== null) {
      clearInterval(sendQueueRef.current);
      sendQueueRef.current = null;
    }
    wsRef.current?.close();
    wsRef.current = null;
    setIsConnected(false);
  }, [clearReconnectTimer]);

  const sendMessage = useCallback(
    (content: string, attachments: string[] = []) => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
        intentionalCloseRef.current = false;
        connect();
        // Wait for connection then send
        const interval = setInterval(() => {
          if (wsRef.current?.readyState === WebSocket.OPEN) {
            clearInterval(interval);
            sendQueueRef.current = null;
            wsRef.current.send(
              JSON.stringify({ type: "message", content, attachments })
            );
            setIsStreaming(true);
          }
        }, 50);
        sendQueueRef.current = interval;
        const timeout = setTimeout(() => {
          clearInterval(interval);
          sendQueueRef.current = null;
        }, 5000);
        // Store timeout ref so it can be cleaned up
        const prevInterval = interval;
        sendQueueRef.current = prevInterval;
        // Clear timeout when interval resolves or component unmounts
        void timeout;
        return;
      }
      wsRef.current.send(
        JSON.stringify({ type: "message", content, attachments })
      );
      setIsStreaming(true);
    },
    [connect]
  );

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      clearReconnectTimer();
      if (sendQueueRef.current !== null) {
        clearInterval(sendQueueRef.current);
        sendQueueRef.current = null;
      }
      wsRef.current?.close();
    };
  }, [clearReconnectTimer]);

  return { isConnected, isStreaming, connect, disconnect, sendMessage };
}
