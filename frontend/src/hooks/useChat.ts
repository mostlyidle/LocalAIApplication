"use client";

import { useCallback, useRef, useState } from "react";
import type { ChatMessage, ChatTaskOptions, ToolCall } from "@/types/chat";
import { useWebSocket } from "./useWebSocket";

export function useChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [streamingContent, setStreamingContent] = useState("");
  const [activeToolCalls, setActiveToolCalls] = useState<Partial<ToolCall>[]>([]);
  const [conversationId, setConversationId] = useState<string | undefined>();
  const activeToolCallsRef = useRef<Partial<ToolCall>[]>([]);
  const streamingContentRef = useRef("");
  const conversationIdRef = useRef<string | undefined>(undefined);

  const handleToken = useCallback((token: string) => {
    streamingContentRef.current += token;
    setStreamingContent(streamingContentRef.current);
  }, []);

  const handleToolCall = useCallback((tool: string, input: Record<string, unknown>) => {
    activeToolCallsRef.current = [
      ...activeToolCallsRef.current,
      { toolName: tool, toolInput: JSON.stringify(input) },
    ];
    setActiveToolCalls(activeToolCallsRef.current);
  }, []);

  const handleToolResult = useCallback((tool: string, output: string) => {
    const index = activeToolCallsRef.current.findLastIndex(
      (tc) => tc.toolName === tool && tc.toolOutput === undefined,
    );
    activeToolCallsRef.current = activeToolCallsRef.current.map((tc, i) =>
      i === index ? { ...tc, toolOutput: output } : tc,
    );
    setActiveToolCalls(activeToolCallsRef.current);
  }, []);

  const handleDone = useCallback(
    (metadata: Record<string, unknown>) => {
      if (streamingContentRef.current) {
        const assistantMsg: ChatMessage = {
          id: crypto.randomUUID(),
          role: "assistant",
          content: streamingContentRef.current,
          agentType: metadata.agent_used
            ? String(metadata.agent_used)
            : metadata.agents_invoked
              ? String((metadata.agents_invoked as string[])[0])
              : undefined,
          toolCalls: activeToolCallsRef.current as ToolCall[],
          timestamp: new Date().toISOString(),
          execution: metadata.execution as ChatMessage["execution"],
        };
        setMessages((msgs) => [...msgs, assistantMsg]);
      }
      streamingContentRef.current = "";
      setStreamingContent("");
      setActiveToolCalls([]);
      activeToolCallsRef.current = [];
      if (metadata.conversation_id) {
        conversationIdRef.current = String(metadata.conversation_id);
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
    streamingContentRef.current = "";
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
    (content: string, attachments: string[] = [], taskOptions?: ChatTaskOptions) => {
      const clientTurnId = crypto.randomUUID();
      const conversationIdForTurn = conversationIdRef.current ?? crypto.randomUUID();
      conversationIdRef.current = conversationIdForTurn;
      const userMsg: ChatMessage = {
        id: clientTurnId,
        clientTurnId,
        role: "user",
        content,
        attachments: attachments.length > 0 ? attachments : undefined,
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, userMsg]);
      setStreamingContent("");
      streamingContentRef.current = "";
      setActiveToolCalls([]);
      activeToolCallsRef.current = [];
      wsSend(content, attachments, conversationIdForTurn, taskOptions, clientTurnId);
    },
    [wsSend]
  );

  const clearMessages = useCallback(() => {
    setMessages([]);
    setStreamingContent("");
    streamingContentRef.current = "";
    setActiveToolCalls([]);
    activeToolCallsRef.current = [];
    setConversationId(undefined);
    conversationIdRef.current = undefined;
  }, []);

  const loadConversation = useCallback((msgs: ChatMessage[], convId: string) => {
    setMessages(msgs);
    setStreamingContent("");
    streamingContentRef.current = "";
    setActiveToolCalls([]);
    activeToolCallsRef.current = [];
    setConversationId(convId);
    conversationIdRef.current = convId;
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
