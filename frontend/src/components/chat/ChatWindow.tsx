"use client";

import { useRef, useEffect, useState, type FormEvent, type ChangeEvent } from "react";
import { Send, Plus, Loader2, Paperclip, X, Image as ImageIcon, History } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { useChat } from "@/hooks/useChat";
import {
  createMemory,
  getAgentCatalog,
  getConversation,
  getConversations,
  updateConversationMemorySettings,
  uploadDocument,
} from "@/lib/api";
import { ACCEPTED_FILE_TYPES, ACTIVE_CONVERSATION_STORAGE_PREFIX, MAX_FILE_SIZE } from "@/lib/constants";
import type { AgentCapability, ChatMessage, ChatTaskOptions } from "@/types/chat";
import type { MemoryRecord } from "@/lib/schemas";
import { useAuth } from "@/components/shared/AuthProvider";
import { MessageBubble } from "./MessageBubble";
import { StreamingText } from "./StreamingText";
import { ToolCallDisplay } from "./ToolCallDisplay";

interface PendingAttachment {
  file: File;
  previewUrl?: string;
  uploadedPath?: string;
  uploading: boolean;
  error?: string;
}

const IMAGE_TYPES = [".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp"];

function restoreMessages(conversation: Awaited<ReturnType<typeof getConversation>>): ChatMessage[] {
  return conversation.messages.map((message) => ({
    id: message.id,
    clientTurnId: message.client_turn_id ?? undefined,
    role: message.role,
    content: message.content,
    agentType: message.agent_type ?? undefined,
    execution: message.execution as ChatMessage["execution"],
    timestamp: message.created_at,
    toolCalls: message.tool_calls.map((toolCall) => ({
      id: toolCall.id,
      toolName: toolCall.tool_name,
      toolInput: JSON.stringify(toolCall.tool_input ?? {}),
      toolOutput: toolCall.tool_output ?? undefined,
      durationMs: toolCall.duration_ms ?? undefined,
    })),
  }));
}

export function ChatWindow() {
  const { account } = useAuth();
  const {
    messages,
    streamingContent,
    activeToolCalls,
    isConnected,
    isStreaming,
    connect,
    sendMessage,
    clearMessages,
    conversationId,
    loadConversation,
  } = useChat();

  const [input, setInput] = useState("");
  const [agents, setAgents] = useState<AgentCapability[]>([]);
  const [selectedAgent, setSelectedAgent] = useState("auto");
  const [collection, setCollection] = useState("documents");
  const [symbol, setSymbol] = useState("");
  const [workspacePath, setWorkspacePath] = useState("");
  const [context, setContext] = useState("");
  const [workflowText, setWorkflowText] = useState("");
  const [selectedModel, setSelectedModel] = useState("");
  const [temperature, setTemperature] = useState(0.1);
  const [profileError, setProfileError] = useState("");
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [conversationError, setConversationError] = useState("");
  const [conversations, setConversations] = useState<Awaited<ReturnType<typeof getConversations>>["conversations"]>([]);
  const [restoringConversation, setRestoringConversation] = useState(false);
  const [excludeFromMemory, setExcludeFromMemory] = useState(false);
  const [recallSettingError, setRecallSettingError] = useState("");
  const [memoryDraft, setMemoryDraft] = useState<{
    message: ChatMessage;
    content: string;
    kind: MemoryRecord["kind"];
    projectScope: string;
  } | null>(null);
  const [savingMemory, setSavingMemory] = useState(false);
  const [memoryError, setMemoryError] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const selectedProfile = agents.find((agent) => agent.name === selectedAgent);
  const conversationStorageKey = account
    ? `${ACTIVE_CONVERSATION_STORAGE_PREFIX}${account.id}`
    : undefined;

  useEffect(() => {
    if (!conversationStorageKey) return;
    const savedConversationId = window.localStorage.getItem(conversationStorageKey);
    if (!savedConversationId) return;

    let active = true;
    setRestoringConversation(true);
    getConversation(savedConversationId)
      .then((conversation) => {
        if (active) {
          loadConversation(restoreMessages(conversation), conversation.id);
          setExcludeFromMemory(conversation.exclude_from_memory);
        }
      })
      .catch((error: unknown) => {
        if (!active) return;
        setConversationError("Could not restore your last conversation. Choose one from history or start a new chat.");
        if ((error as { statusCode?: number })?.statusCode === 404) {
          window.localStorage.removeItem(conversationStorageKey);
        }
      })
      .finally(() => {
        if (active) setRestoringConversation(false);
      });

    return () => {
      active = false;
    };
  }, [conversationStorageKey, loadConversation]);

  useEffect(() => {
    if (conversationId && conversationStorageKey) {
      window.localStorage.setItem(conversationStorageKey, conversationId);
    }
  }, [conversationId, conversationStorageKey]);

  useEffect(() => {
    if (!historyOpen) return;
    let active = true;
    setHistoryLoading(true);
    getConversations()
      .then((result) => {
        if (active) {
          setConversations(result.conversations);
          setConversationError("");
        }
      })
      .catch(() => {
        if (active) setConversationError("Could not load your saved conversations.");
      })
      .finally(() => {
        if (active) setHistoryLoading(false);
      });
    return () => {
      active = false;
    };
  }, [historyOpen, conversationId]);

  const startNewConversation = () => {
    clearMessages();
    setExcludeFromMemory(false);
    setRecallSettingError("");
    setConversationError("");
    if (conversationStorageKey) window.localStorage.removeItem(conversationStorageKey);
  };

  const handleRecallExclusionChange = async (exclude: boolean) => {
    if (!conversationId) return;
    const previous = excludeFromMemory;
    setExcludeFromMemory(exclude);
    setRecallSettingError("");
    try {
      await updateConversationMemorySettings(conversationId, { exclude_from_memory: exclude });
    } catch (cause) {
      setExcludeFromMemory(previous);
      setRecallSettingError(cause instanceof Error ? cause.message : "Could not update recall settings.");
    }
  };

  const rememberMessage = (message: ChatMessage) => {
    setMemoryError("");
    setMemoryDraft({ message, content: message.content, kind: "fact", projectScope: "" });
  };

  const saveMemory = async (event: FormEvent) => {
    event.preventDefault();
    if (!memoryDraft || !memoryDraft.content.trim()) return;
    setSavingMemory(true);
    setMemoryError("");
    try {
      await createMemory({
        kind: memoryDraft.kind,
        content: memoryDraft.content.trim(),
        ...(memoryDraft.projectScope.trim() ? { project_scope: memoryDraft.projectScope.trim() } : {}),
        ...(conversationId ? { source_conversation_id: conversationId } : {}),
        ...(memoryDraft.message.clientTurnId
          ? { source_client_turn_id: memoryDraft.message.clientTurnId }
          : { source_message_id: memoryDraft.message.id }),
      });
      setMemoryDraft(null);
    } catch (cause) {
      setMemoryError(cause instanceof Error ? cause.message : "Could not save this memory.");
    } finally {
      setSavingMemory(false);
    }
  };

  const selectConversation = async (id: string) => {
    setRestoringConversation(true);
    setConversationError("");
    try {
      const conversation = await getConversation(id);
      loadConversation(restoreMessages(conversation), conversation.id);
      setExcludeFromMemory(conversation.exclude_from_memory);
      setRecallSettingError("");
      if (conversationStorageKey) {
        window.localStorage.setItem(conversationStorageKey, conversation.id);
      }
      setHistoryOpen(false);
    } catch {
      setConversationError("Could not open that conversation. Refresh the list and try again.");
    } finally {
      setRestoringConversation(false);
    }
  };

  useEffect(() => {
    getAgentCatalog()
      .then((catalog) => setAgents(catalog.agents as AgentCapability[]))
      .catch(() => setAgents([]));
  }, []);

  useEffect(() => {
    const defaultModel = selectedProfile?.inference?.defaults.model ?? "";
    const installedModel = selectedProfile?.inference?.allowed_models.find(
      (model) => selectedProfile.model_availability?.[model] === true,
    );
    setSelectedModel(
      selectedProfile?.model_availability?.[defaultModel] === false && installedModel
        ? installedModel : defaultModel,
    );
    setTemperature(selectedProfile?.inference?.defaults.temperature ?? 0.1);
  }, [
    selectedAgent,
    selectedProfile?.inference?.defaults.model,
    selectedProfile?.inference?.defaults.temperature,
    selectedProfile?.inference?.allowed_models,
    selectedProfile?.model_availability,
  ]);

  // Auto-scroll to bottom
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, streamingContent, activeToolCalls]);

  // Connect on mount
  useEffect(() => {
    connect();
  }, [connect]);

  // Cleanup preview URLs
  useEffect(() => {
    return () => {
      attachments.forEach((a) => {
        if (a.previewUrl) URL.revokeObjectURL(a.previewUrl);
      });
    };
  }, [attachments]);

  const handleFileSelect = async (e: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    if (files.length === 0) return;

    // Reset input so the same file can be re-selected
    e.target.value = "";

    for (const file of files) {
      if (file.size > MAX_FILE_SIZE) {
        setAttachments((prev) => [
          ...prev,
          { file, uploading: false, error: "File too large (max 50MB)" },
        ]);
        continue;
      }

      const ext = `.${file.name.split(".").pop()?.toLowerCase()}`;
      const isImage = IMAGE_TYPES.includes(ext);
      const previewUrl = isImage ? URL.createObjectURL(file) : undefined;

      const attachment: PendingAttachment = {
        file,
        previewUrl,
        uploading: true,
      };

      setAttachments((prev) => [...prev, attachment]);

      // Upload immediately
      try {
        const result = await uploadDocument(file);
        setAttachments((prev) =>
          prev.map((a) =>
            a.file === file
              ? { ...a, uploading: false, uploadedPath: result.id }
              : a
          )
        );
      } catch {
        setAttachments((prev) =>
          prev.map((a) =>
            a.file === file
              ? { ...a, uploading: false, error: "Upload failed" }
              : a
          )
        );
      }
    }
  };

  const removeAttachment = (index: number) => {
    setAttachments((prev) => {
      const removed = prev[index];
      if (removed?.previewUrl) URL.revokeObjectURL(removed.previewUrl);
      return prev.filter((_, i) => i !== index);
    });
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const trimmed = input.trim();
    if ((!trimmed && attachments.length === 0) || isStreaming) return;

    // Collect uploaded attachment IDs
    const uploadedIds = attachments
      .filter((a) => a.uploadedPath && !a.error)
      .map((a) => a.uploadedPath!);

    const message = trimmed || "Analyze the attached file(s).";
    setProfileError("");
    const options: ChatTaskOptions = {};
    if (selectedProfile) {
      options.agent_name = selectedProfile.name;
      if (["image_analysis", "image_fraud"].includes(selectedProfile.target)) {
        const hasUploadedImage = attachments.some((attachment) =>
          attachment.uploadedPath && !attachment.error &&
          IMAGE_TYPES.includes(`.${attachment.file.name.split(".").pop()?.toLowerCase()}`),
        );
        if (!hasUploadedImage) {
          setProfileError("Attach an uploaded image for this profile.");
          return;
        }
      }
      if (selectedProfile.target === "rag") options.collection = collection.trim() || "documents";
      if (selectedProfile.target === "stock_research") {
        if (!symbol.trim()) {
          setProfileError("Enter a ticker symbol for stock research.");
          return;
        }
        options.symbol = symbol.trim();
        options.context = context.trim() || undefined;
      }
      if (selectedProfile.target === "software_engineer") {
        options.workspace_path = workspacePath.trim() || undefined;
      }
      if (selectedProfile.name === "document_analytics") {
        options.context = context.trim() || undefined;
      }
      if (selectedProfile.target === "image_generation") {
        try {
          const parsed: unknown = JSON.parse(workflowText);
          if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
            throw new Error("Workflow must be a JSON object.");
          }
          options.workflow = parsed as Record<string, unknown>;
        } catch {
          setProfileError("Paste a valid ComfyUI API workflow JSON object.");
          return;
        }
      }
      if (selectedProfile.inference) {
        const model = selectedModel || selectedProfile.inference.defaults.model;
        if (selectedProfile.model_availability?.[model] === false) {
          setProfileError(`Install ${model} in Ollama, then reload the page, or choose an installed model.`);
          return;
        }
        options.inference = {
          model,
          temperature,
        };
      }
    }
    if (selectedProfile) sendMessage(message, uploadedIds, options);
    else sendMessage(message, uploadedIds);
    setInput("");
    setAttachments([]);
    textareaRef.current?.focus();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const hasUploadingFiles = attachments.some((a) => a.uploading);
  const hasReadyAttachments = attachments.some(
    (a) => a.uploadedPath && !a.error
  );

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b px-4 py-2">
        <div className="flex items-center gap-3">
          <span className="text-sm font-medium">{conversationId ? "Saved conversation" : "New conversation"}</span>
          {conversationId && (
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground" title="This affects cross-chat recall, not the saved transcript or memories you choose to save manually.">
              <input
                type="checkbox"
                aria-label="Exclude this chat from past-chat recall"
                checked={excludeFromMemory}
                onChange={(event) => void handleRecallExclusionChange(event.target.checked)}
                disabled={isStreaming || restoringConversation}
                className="h-3.5 w-3.5 accent-primary"
              />
              Exclude from past-chat recall
            </label>
          )}
        </div>
        <div className="flex gap-2">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => setHistoryOpen((open) => !open)}
            disabled={restoringConversation}
            aria-expanded={historyOpen}
          >
            <History className="mr-2 h-4 w-4" />
            History
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={startNewConversation} disabled={isStreaming || restoringConversation}>
            <Plus className="mr-2 h-4 w-4" />
            New chat
          </Button>
        </div>
      </div>
      {recallSettingError && <p role="alert" className="border-b px-4 py-2 text-xs text-destructive">{recallSettingError}</p>}
      {historyOpen && (
        <div aria-label="Conversation history" className="max-h-48 space-y-1 overflow-y-auto border-b p-2">
          {historyLoading && <p className="px-2 py-1 text-xs text-muted-foreground">Loading conversations…</p>}
          {!historyLoading && conversations.length === 0 && !conversationError && (
            <p className="px-2 py-1 text-xs text-muted-foreground">No saved conversations yet.</p>
          )}
          {conversations.map((conversation) => (
            <button
              key={conversation.id}
              type="button"
              onClick={() => void selectConversation(conversation.id)}
              disabled={restoringConversation || isStreaming}
              className={`flex w-full items-center justify-between gap-3 rounded-md px-2 py-2 text-left text-sm hover:bg-muted disabled:opacity-50 ${conversation.id === conversationId ? "bg-muted" : ""}`}
            >
              <span className="truncate">{conversation.title || "Untitled conversation"}</span>
              <span className="shrink-0 text-xs text-muted-foreground">
                {conversation.message_count} · {new Date(conversation.last_message_at).toLocaleDateString()}
              </span>
            </button>
          ))}
        </div>
      )}
      {conversationError && <p role="alert" className="border-b px-4 py-2 text-xs text-destructive">{conversationError}</p>}
      {/* Messages area */}
      <ScrollArea ref={scrollRef} className="flex-1 p-4">
        <div className="mx-auto max-w-3xl space-y-4">
          {messages.length === 0 && !isStreaming && (
            <div className="flex h-64 flex-col items-center justify-center text-center text-muted-foreground">
              <p className="text-lg font-medium">Start a conversation</p>
              <p className="mt-1 text-sm">
                Ask anything — I can query databases, analyze documents,
                search your knowledge base, and more.
              </p>
              <p className="mt-2 text-xs">
                <Paperclip className="mr-1 inline h-3 w-3" />
                Attach images or documents for analysis
              </p>
            </div>
          )}
          {messages.map((msg) => (
            <MessageBubble
              key={msg.id}
              message={msg}
              canRemember={!isStreaming}
              onRemember={rememberMessage}
              onOpenConversation={(sourceId) => void selectConversation(sourceId)}
              canOpenSources={!isStreaming && !restoringConversation}
            />
          ))}
          {/* Active tool calls during streaming */}
          {activeToolCalls.length > 0 && (
            <div className="flex w-full justify-start">
              <div className="max-w-[80%] space-y-2">
                {activeToolCalls.map((tc, i) => (
                  <ToolCallDisplay key={i} toolCall={tc} />
                ))}
              </div>
            </div>
          )}
          {/* Streaming text */}
          <StreamingText content={streamingContent} />
        </div>
      </ScrollArea>

      {/* Attachment preview strip */}
      {attachments.length > 0 && (
        <div className="border-t bg-muted/50 px-4 py-2">
          <div className="mx-auto flex max-w-3xl gap-2 overflow-x-auto">
            {attachments.map((att, idx) => (
              <div
                key={idx}
                className="relative flex items-center gap-2 rounded-md border bg-background px-2 py-1"
              >
                {att.previewUrl ? (
                  <img
                    src={att.previewUrl}
                    alt={att.file.name}
                    className="h-10 w-10 rounded object-cover"
                  />
                ) : (
                  <ImageIcon className="h-4 w-4 text-muted-foreground" />
                )}
                <div className="flex flex-col">
                  <span className="max-w-[120px] truncate text-xs">
                    {att.file.name}
                  </span>
                  {att.uploading && (
                    <span className="flex items-center gap-1 text-[10px] text-muted-foreground">
                      <Loader2 className="h-2.5 w-2.5 animate-spin" />
                      Uploading...
                    </span>
                  )}
                  {att.error && (
                    <span className="text-[10px] text-destructive">
                      {att.error}
                    </span>
                  )}
                  {att.uploadedPath && !att.error && (
                    <Badge variant="secondary" className="h-4 text-[10px]">
                      Ready
                    </Badge>
                  )}
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-5 w-5"
                  onClick={() => removeAttachment(idx)}
                >
                  <X className="h-3 w-3" />
                </Button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Input area */}
      <div className="border-t bg-background p-4">
        {profileError && <div className="mx-auto mb-2 max-w-3xl text-xs text-destructive">{profileError}</div>}
        <div className="mx-auto mb-2 flex max-w-3xl flex-wrap items-center gap-2">
          <label className="text-xs text-muted-foreground" htmlFor="agent-profile">Agent</label>
          <select
            id="agent-profile"
            aria-label="Agent profile"
            value={selectedAgent}
            onChange={(event) => { setSelectedAgent(event.target.value); setProfileError(""); }}
            disabled={isStreaming}
            className="h-8 rounded-md border bg-background px-2 text-xs"
          >
            <option value="auto">Auto select</option>
            {agents.map((agent) => (
              <option key={agent.name} value={agent.name}>
                {agent.name.replaceAll("_", " ")}{agent.default_for_target ? " · default" : ""}
              </option>
            ))}
          </select>
          {selectedProfile?.inference && (
            <>
              <label className="sr-only" htmlFor="agent-model">Model</label>
              <select
                id="agent-model"
                aria-label="Agent model"
                value={selectedModel}
                onChange={(event) => setSelectedModel(event.target.value)}
                disabled={isStreaming}
                className="h-8 max-w-52 rounded-md border bg-background px-2 text-xs"
              >
                {selectedProfile.inference.allowed_models.map((model) => {
                  const available = selectedProfile.model_availability?.[model];
                  const label = available === true ? " (installed)"
                    : available === false ? " (not installed)"
                    : available === null ? " (availability unknown)" : "";
                  return <option key={model} value={model} disabled={available === false}>{model}{label}</option>;
                })}
              </select>
              <label className="sr-only" htmlFor="agent-temperature">Temperature</label>
              <input
                id="agent-temperature"
                aria-label="Agent temperature"
                type="number"
                min={selectedProfile.inference.limits.temperature.minimum}
                max={selectedProfile.inference.limits.temperature.maximum}
                step="0.1"
                value={temperature}
                onChange={(event) => setTemperature(Number(event.target.value))}
                disabled={isStreaming}
                className="h-8 w-20 rounded-md border bg-background px-2 text-xs"
              />
            </>
          )}
          {selectedProfile?.target === "rag" && (
            <input aria-label="RAG collection" value={collection} onChange={(event) => setCollection(event.target.value)} placeholder="Collection" className="h-8 w-36 rounded-md border bg-background px-2 text-xs" />
          )}
          {selectedProfile?.target === "stock_research" && (
            <>
              <input aria-label="Ticker symbol" value={symbol} onChange={(event) => setSymbol(event.target.value)} placeholder="Ticker (e.g. AAPL)" className="h-8 w-36 rounded-md border bg-background px-2 text-xs" />
              <input aria-label="Research context" value={context} onChange={(event) => setContext(event.target.value)} placeholder="Optional context" className="h-8 min-w-36 flex-1 rounded-md border bg-background px-2 text-xs" />
            </>
          )}
          {selectedProfile?.target === "software_engineer" && (
            <input aria-label="Workspace path" value={workspacePath} onChange={(event) => setWorkspacePath(event.target.value)} placeholder="Workspace subpath (optional)" className="h-8 min-w-48 flex-1 rounded-md border bg-background px-2 text-xs" />
          )}
          {selectedProfile?.name === "document_analytics" && (
            <input aria-label="Document context" value={context} onChange={(event) => setContext(event.target.value)} placeholder="Optional text context" className="h-8 min-w-48 flex-1 rounded-md border bg-background px-2 text-xs" />
          )}
          {selectedProfile?.target === "image_generation" && (
            <textarea aria-label="ComfyUI workflow" value={workflowText} onChange={(event) => setWorkflowText(event.target.value)} placeholder="Paste exported ComfyUI API workflow JSON" rows={2} className="min-h-8 min-w-48 flex-1 rounded-md border bg-background px-2 py-1 text-xs" />
          )}
        </div>
        <form
          onSubmit={handleSubmit}
          className="mx-auto flex max-w-3xl items-end gap-2"
        >
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-10 w-10 shrink-0"
            onClick={startNewConversation}
            disabled={isStreaming || restoringConversation}
            title="New conversation"
          >
            <Plus className="h-4 w-4" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-10 w-10 shrink-0"
            onClick={() => fileInputRef.current?.click()}
            disabled={isStreaming}
            title="Attach file"
          >
            <Paperclip className="h-4 w-4" />
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={ACCEPTED_FILE_TYPES.join(",")}
            className="hidden"
            onChange={handleFileSelect}
          />
          <Textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              attachments.length > 0
                ? "Describe what to do with the attached file(s)..."
                : "Type a message... (Shift+Enter for new line)"
            }
            className="min-h-[44px] max-h-32 resize-none"
            rows={1}
            disabled={isStreaming}
          />
          <Button
            type="submit"
            size="icon"
            className="h-10 w-10 shrink-0"
            disabled={
              (!input.trim() && !hasReadyAttachments) ||
              isStreaming ||
              hasUploadingFiles
            }
          >
            {isStreaming ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
          </Button>
        </form>
        <div className="mx-auto mt-2 max-w-3xl text-center text-[10px] text-muted-foreground">
          {isConnected ? "Connected" : "Disconnected"} — Responses are generated locally by Ollama
        </div>
      </div>
      {memoryDraft && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <form
            role="dialog"
            aria-modal="true"
            aria-labelledby="remember-title"
            onSubmit={saveMemory}
            className="w-full max-w-lg space-y-4 rounded-lg border bg-background p-5 shadow-lg"
          >
            <div>
              <h2 id="remember-title" className="font-semibold">Remember this</h2>
              <p className="text-sm text-muted-foreground">Review the exact text your account will save.</p>
            </div>
            {memoryError && <p role="alert" className="text-sm text-destructive">{memoryError}</p>}
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="space-y-1 text-sm" htmlFor="remember-kind">
                Type
                <select id="remember-kind" value={memoryDraft.kind} onChange={(event) => setMemoryDraft({ ...memoryDraft, kind: event.target.value as MemoryRecord["kind"] })} className="h-9 w-full rounded-md border bg-background px-3">
                  <option value="fact">Fact</option>
                  <option value="preference">Preference</option>
                  <option value="project_decision">Project decision</option>
                </select>
              </label>
              <label className="space-y-1 text-sm" htmlFor="remember-project">
                Project (optional)
                <input id="remember-project" value={memoryDraft.projectScope} maxLength={128} onChange={(event) => setMemoryDraft({ ...memoryDraft, projectScope: event.target.value })} className="h-9 w-full rounded-md border bg-background px-3" />
              </label>
            </div>
            <label className="block space-y-1 text-sm" htmlFor="remember-content">
              Memory text
              <textarea id="remember-content" value={memoryDraft.content} maxLength={4000} rows={4} onChange={(event) => setMemoryDraft({ ...memoryDraft, content: event.target.value })} className="w-full rounded-md border bg-background px-3 py-2" />
            </label>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={() => setMemoryDraft(null)} disabled={savingMemory}>Cancel</Button>
              <Button type="submit" disabled={savingMemory || !memoryDraft.content.trim()}>
                {savingMemory && <Loader2 className="animate-spin" />} Save memory
              </Button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
