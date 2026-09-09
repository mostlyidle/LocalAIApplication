"use client";

import { useCallback, useRef, useState } from "react";
import type { ChatMessage, ToolCall } from "@/types/chat";
import { useWebSocket } from "./useWebSocket";

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streamingContent, setStreamingContent] = useState("");
  const [activeToolCalls, setActiveToolCalls] = useState<Partial<ToolCall>[]>([]);
  const [conversationId, setConversationId] = useState<string | undefined>();
  const activeToolCallsRef = useRef<Partial<ToolCall>[]>([]);

  const handleToken = useCallback((token: string) => {
    setStreamingContent((prev) => prev + token);
  }, []);

  const handleToolCall = useCallback((tool: string, input: Record<string, unknown>) => {
    setActiveToolCalls((prev) => {
      const next = [
        ...prev,
        { toolName: tool, toolInput: JSON.stringify(input) },
      ];
      activeToolCallsRef.current = next;
      return next;
    });
  }, []);

  const handleToolResult = useCallback((tool: string, output: string) => {
    setActiveToolCalls((prev) => {
      const next = prev.map((tc) =>
        tc.toolName === tool && !tc.toolOutput
          ? { ...tc, toolOutput: output }
          : tc
      );
      activeToolCallsRef.current = next;
      return next;
    });
  }, []);

  const handleDone = useCallback(
    (metadata: Record<string, unknown>) => {
      setStreamingContent((prev) => {
        if (prev) {
          const assistantMsg: ChatMessage = {
            id: crypto.randomUUID(),
            role: "assistant",
            content: prev,
            agentType: metadata.agents_invoked
              ? String((metadata.agents_invoked as string[])[0])
              : undefined,
            toolCalls: activeToolCallsRef.current as ToolCall[],
            timestamp: new Date().toISOString(),
          };
          setMessages((msgs) => [...msgs, assistantMsg]);
        }
        return "";
      });
      setActiveToolCalls([]);
      activeToolCallsRef.current = [];
      if (metadata.conversation_id) {
        setConversationId(String(metadata.conversation_id));
      }
    },
    []
  );

  const handleError = useCallback((error: string) => {
    const errorMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "assistant",
      content: `Error: ${error}`,
      timestamp: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, errorMsg]);
    setStreamingContent("");
    setActiveToolCalls([]);
    activeToolCallsRef.current = [];
  }, []);

  const { isConnected, isStreaming, connect, sendMessage: wsSend } =
    useWebSocket({
      onToken: handleToken,
      onToolCall: handleToolCall,
      onToolResult: handleToolResult,
      onDone: handleDone,
      onError: handleError,
    });

  const sendMessage = useCallback(
    (content: string, attachments: string[] = []) => {
      const userMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: "user",
        content,
        attachments: attachments.length > 0 ? attachments : undefined,
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, userMsg]);
      setStreamingContent("");
      setActiveToolCalls([]);
      activeToolCallsRef.current = [];
      wsSend(content, attachments);
    },
    [wsSend]
  );

  const clearMessages = useCallback(() => {
    setMessages([]);
    setStreamingContent("");
    setActiveToolCalls([]);
    activeToolCallsRef.current = [];
    setConversationId(undefined);
  }, []);

  const loadConversation = useCallback((msgs: ChatMessage[], convId: string) => {
    setMessages(msgs);
    setConversationId(convId);
  }, []);

  return {
    messages,
    streamingContent,
    activeToolCalls,
    conversationId,
    isConnected,
    isStreaming,
    connect,
    sendMessage,
    clearMessages,
    loadConversation,
  };
}
