"use client";

import { useRef, useEffect, useState, type FormEvent, type ChangeEvent, type ReactNode } from "react";
import Link from "next/link";
import { Send, Plus, Loader2, Paperclip, X, Image as ImageIcon, History, Sparkles, Lightbulb, BookOpen, ListChecks, PenLine, SlidersHorizontal, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useChat } from "@/hooks/useChat";
import {
  createMemory,
  getRAGCollections,
  getRAGContainers,
  getAgentCatalogWithArchived,
  getConversation,
  getConversations,
  getDocuments,
  updateConversationMemorySettings,
  uploadDocument,
} from "@/lib/api";
import { ACCEPTED_FILE_TYPES, ACTIVE_CONVERSATION_STORAGE_PREFIX, AGENT_LABELS, MAX_FILE_SIZE } from "@/lib/constants";
import type { AgentCapability, ChatMessage, ChatTaskOptions } from "@/types/chat";
import type { RAGContainer } from "@/lib/api";
import type { MemoryRecord } from "@/lib/schemas";
import { useAuth } from "@/components/shared/AuthProvider";
import { BrandMark } from "@/components/shared/BrandMark";
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
const starterPrompts = [
  { title: "Spark an idea", hint: "Find a fresh perspective", prompt: "Help me brainstorm a few creative ideas for ", icon: Lightbulb, tone: "bg-peach-soft text-peach-ink" },
  { title: "Explain something", hint: "Make the complex feel simple", prompt: "Explain this in simple terms, with an example: ", icon: BookOpen, tone: "bg-sky-soft text-sky-ink" },
  { title: "Make a plan", hint: "One small step at a time", prompt: "Help me make a practical, step-by-step plan for ", icon: ListChecks, tone: "bg-mint-soft text-mint-ink" },
  { title: "Polish my writing", hint: "Give your words a little shine", prompt: "Help me improve the clarity and tone of this writing: ", icon: PenLine, tone: "bg-rose-soft text-rose-ink" },
];

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
  const [ragContainers, setRagContainers] = useState<RAGContainer[]>([]);
  const [ragCollections, setRagCollections] = useState<Array<{ name: string; count: number }>>([]);
  const [symbol, setSymbol] = useState("");
  const [workspacePath, setWorkspacePath] = useState("");
  const [context, setContext] = useState("");
  const [workflowText, setWorkflowText] = useState("");
  const [selectedModel, setSelectedModel] = useState("");
  const [temperature, setTemperature] = useState(0.1);
  const [profileError, setProfileError] = useState<ReactNode>("");
  const [optionsOpen, setOptionsOpen] = useState(false);
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyQuery, setHistoryQuery] = useState("");
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
  const selectedProfile = agents.find((agent) => agent.name === selectedAgent && !agent.archived);
  const agentDisplayNames = Object.fromEntries(agents.map((agent) => [
    agent.name,
    agent.display_name || AGENT_LABELS[agent.name] || agent.name.replaceAll("_", " "),
  ]));
  const filteredConversations = conversations.filter((conversation) =>
    (conversation.title || "Untitled conversation").toLowerCase().includes(historyQuery.trim().toLowerCase()),
  );

  useEffect(() => {
    const documentId = new URLSearchParams(window.location.search).get("documentId");
    if (!documentId) return;

    let active = true;
    getDocuments().then(({ documents }) => {
      const document = documents.find((item) => item.id === documentId);
      if (!active || !document) return;
      setAttachments((current) => current.some((item) => item.uploadedPath === document.id)
        ? current
        : [...current, {
            file: new File([], document.filename),
            uploadedPath: document.id,
            uploading: false,
          }]);
      setInput((current) => current || `Help me understand ${document.filename}.`);
    }).catch(() => {
      if (active) setProfileError("Could not prepare the selected document for chat.");
    });
    return () => { active = false; };
  }, []);
  const conversationStorageKey = account
    ? `${ACTIVE_CONVERSATION_STORAGE_PREFIX}${account.id}`
    : undefined;

  useEffect(() => {
    let active = true;
    void Promise.all([getRAGContainers(), getRAGCollections()])
      .then(([containers, collectionResponse]) => {
        if (!active) return;
        setRagContainers(containers);
        setRagCollections(collectionResponse.collections);
        setCollection((current) => {
          if (
            current &&
            (containers.some((item) => item.name === current) ||
              collectionResponse.collections.some((item) => item.name === current))
          ) return current;
          return containers[0]?.name || collectionResponse.collections[0]?.name || "";
        });
      })
      .catch(() => {
        if (active) setCollection("");
      });
    return () => { active = false; };
  }, []);

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
    getAgentCatalogWithArchived()
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
    const viewport = scrollRef.current?.querySelector("[data-radix-scroll-area-viewport]");
    if (viewport) {
      viewport.scrollTop = messages.length || streamingContent || activeToolCalls.length
        ? viewport.scrollHeight : 0;
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
    if ((!trimmed && attachments.length === 0) || isStreaming || restoringConversation) return;

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
      if (selectedProfile.target === "rag") {
        if (!collection) {
          setProfileError(
            <span>
              No vector container selected for RAG search.
              <Link href="/rag" className="ml-2 font-semibold underline hover:text-foreground">
                Open RAG Containers →
              </Link>
            </span>,
          );
          return;
        }
        options.collection = collection;
      }
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
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b bg-card/50 px-4 py-3 sm:px-6">
        <div className="flex min-w-0 flex-wrap items-center gap-3">
          <span className="flex items-center gap-2 text-sm font-semibold"><Sparkles className="size-4 text-primary" aria-hidden="true" />{conversationId ? "Saved conversation" : "New conversation"}</span>
          {conversationId && (
            <label className="flex min-h-9 cursor-pointer items-center gap-2 text-xs text-muted-foreground" title="This affects cross-chat recall, not the saved transcript or memories you choose to save manually.">
              <input
                type="checkbox"
                aria-label="Exclude this chat from past-chat recall"
                checked={excludeFromMemory}
                onChange={(event) => void handleRecallExclusionChange(event.target.checked)}
                disabled={isStreaming || restoringConversation}
                className="h-4 w-4 accent-primary"
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
            className="min-h-11 rounded-xl"
            onClick={() => setHistoryOpen((open) => !open)}
            disabled={restoringConversation}
            aria-expanded={historyOpen}
          >
            <History className="h-4 w-4" aria-hidden="true" />
            History
          </Button>
          <Button type="button" variant="outline" size="sm" className="min-h-11 rounded-xl" onClick={startNewConversation} disabled={isStreaming || restoringConversation}>
            <Plus className="h-4 w-4" aria-hidden="true" />
            New chat
          </Button>
        </div>
      </div>
      {recallSettingError && <p role="alert" className="border-b px-4 py-2 text-xs text-destructive">{recallSettingError}</p>}
      <Sheet open={historyOpen} onOpenChange={setHistoryOpen}>
        <SheetContent aria-label="Conversation history" className="gap-0 p-0 sm:max-w-md">
          <SheetHeader className="border-b">
            <SheetTitle>Conversation history</SheetTitle>
            <SheetDescription>Return to a conversation from your saved chats.</SheetDescription>
          </SheetHeader>
          <div className="border-b p-3">
            <label htmlFor="conversation-search" className="sr-only">Search conversations</label>
            <div className="flex items-center gap-2 rounded-lg border bg-card px-3">
              <Search className="size-4 text-muted-foreground" aria-hidden="true" />
              <input id="conversation-search" value={historyQuery} onChange={(event) => setHistoryQuery(event.target.value)} placeholder="Search conversations" className="h-11 min-w-0 flex-1 bg-transparent text-sm outline-none" />
            </div>
          </div>
          <div className="min-h-0 flex-1 space-y-1 overflow-y-auto p-3">
            {historyLoading && <p className="px-2 py-1 text-sm text-muted-foreground">Loading conversations…</p>}
            {!historyLoading && conversations.length === 0 && !conversationError && (
              <p className="px-2 py-1 text-sm text-muted-foreground">No saved conversations yet.</p>
            )}
            {!historyLoading && conversations.length > 0 && filteredConversations.length === 0 && (
              <p className="px-2 py-1 text-sm text-muted-foreground">No conversations match that search.</p>
            )}
            {filteredConversations.map((conversation) => (
              <button
                key={conversation.id}
                type="button"
                onClick={() => void selectConversation(conversation.id)}
                disabled={restoringConversation || isStreaming}
                className={`flex min-h-11 w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left text-sm hover:bg-muted disabled:opacity-50 ${conversation.id === conversationId ? "bg-muted" : ""}`}
              >
                <span className="truncate">{conversation.title || "Untitled conversation"}</span>
                <span className="shrink-0 text-xs text-muted-foreground">
                  {conversation.message_count} · {new Date(conversation.last_message_at).toLocaleDateString()}
                </span>
              </button>
            ))}
          </div>
        </SheetContent>
      </Sheet>
      {conversationError && <p role="alert" className="border-b px-4 py-2 text-xs text-destructive">{conversationError}</p>}
      {/* Messages area */}
      <ScrollArea ref={scrollRef} className="min-h-0 flex-1 px-4 py-5 sm:px-6">
        <div className="mx-auto max-w-3xl space-y-5">
          {restoringConversation && <p role="status" className="text-center text-sm text-muted-foreground">Opening your conversation…</p>}
          {messages.length === 0 && !isStreaming && (
            <div className="mx-auto flex max-w-2xl flex-col items-center py-4 text-center sm:py-8">
              <BrandMark className="mb-3 h-24 w-24 sm:h-28 sm:w-28" />
              <span className="rounded-full bg-mint-soft px-3 py-1 text-xs font-semibold text-mint-ink">A little curiosity goes a long way</span>
              <h1 className="mt-4 text-2xl font-bold tracking-tight sm:text-3xl">Hello, curious human.</h1>
              <p className="mt-2 max-w-md text-sm leading-relaxed text-muted-foreground">
                What shall we explore today? Bring a question, an idea, or a file.<br className="hidden sm:block" /> Your local AI team is here to help.
              </p>
              <h2 className="mt-6 text-xs font-semibold text-muted-foreground">Start a conversation</h2>
              <div className="mt-3 grid w-full gap-3 sm:grid-cols-2">
                {starterPrompts.map((starter) => (
                  <button key={starter.title} type="button" disabled={restoringConversation} onClick={() => { setInput(starter.prompt); textareaRef.current?.focus(); }} className="flex items-center gap-3 rounded-2xl border bg-card p-4 text-left transition-colors hover:border-primary/50 hover:bg-accent/40 disabled:opacity-50">
                    <span className={`grid size-10 shrink-0 place-items-center rounded-xl ${starter.tone}`}><starter.icon className="size-5" aria-hidden="true" /></span>
                    <span><span className="block text-sm font-semibold">{starter.title}</span><span className="mt-0.5 block text-xs text-muted-foreground">{starter.hint}</span></span>
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((msg) => (
            <MessageBubble
              key={msg.id}
              message={msg}
              agentDisplayNames={agentDisplayNames}
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
          {isStreaming && !streamingContent && activeToolCalls.length === 0 && (
            <div role="status" className="flex items-center gap-3 rounded-2xl border bg-card p-4 text-sm text-muted-foreground"><BrandMark className="size-9" /><Loader2 className="size-4 animate-spin text-primary" aria-hidden="true" />Your agent is thinking…</div>
          )}
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
                  className="h-9 w-9"
                  aria-label={`Remove ${att.file.name}`}
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
      <div className="shrink-0 px-3 pb-3 pt-2 sm:px-6 sm:pb-5">
        {profileError && <div role="alert" className="mx-auto mb-2 max-w-3xl rounded-xl bg-destructive/10 p-3 text-sm text-destructive">{profileError}</div>}
        <div className="mx-auto mb-2 flex max-w-3xl flex-wrap items-center gap-2">
          <label className="flex items-center gap-1.5 text-xs font-semibold text-muted-foreground" htmlFor="agent-profile"><Sparkles className="size-3.5" aria-hidden="true" /> Agent</label>
          <select
            id="agent-profile"
            aria-label="Agent profile"
            value={selectedAgent}
            onChange={(event) => { setSelectedAgent(event.target.value); setProfileError(""); }}
            disabled={isStreaming}
            className="h-11 max-w-full rounded-xl border border-input bg-card px-3 text-base sm:text-sm"
          >
            <option value="auto">Auto select</option>
            {agents.filter((agent) => !agent.archived).map((agent) => (
              <option key={agent.name} value={agent.name}>
                {AGENT_LABELS[agent.name] ?? (agent.display_name || agent.name.replaceAll("_", " "))}{agent.default_for_target ? " · default" : ""}
              </option>
            ))}
          </select>
          <Button type="button" variant="ghost" size="sm" className="min-h-11 rounded-xl" onClick={() => setOptionsOpen((open) => !open)} aria-expanded={optionsOpen} aria-controls="agent-options">
            <SlidersHorizontal className="size-3.5" aria-hidden="true" />
            Options
          </Button>
        </div>
        {optionsOpen && <div id="agent-options" className="mx-auto mb-3 flex max-w-3xl flex-wrap items-end gap-3 rounded-xl border bg-muted/40 p-3">
          {selectedProfile?.inference && (
            <>
              <label className="text-xs text-muted-foreground" htmlFor="agent-model">Model</label>
              <select
                id="agent-model"
                aria-label="Agent model"
                value={selectedModel}
                onChange={(event) => setSelectedModel(event.target.value)}
                disabled={isStreaming}
                className="h-11 max-w-full rounded-xl border border-input bg-card px-3 text-base sm:text-sm sm:max-w-52"
              >
                {selectedProfile.inference.allowed_models.map((model) => {
                  const available = selectedProfile.model_availability?.[model];
                  const label = available === true ? " (installed)"
                    : available === false ? " (not installed)"
                    : available === null ? " (availability unknown)" : "";
                  return <option key={model} value={model} disabled={available === false}>{model}{label}</option>;
                })}
              </select>
              <label className="text-xs text-muted-foreground" htmlFor="agent-temperature">Temperature</label>
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
                className="h-11 w-20 rounded-xl border border-input bg-card px-3 text-base sm:text-sm"
              />
            </>
          )}
          {selectedProfile?.target === "rag" && (
            <label className="flex flex-col gap-1 text-xs text-muted-foreground">
              Search index
              <select
                aria-label="Search index"
                value={collection}
                onChange={(event) => setCollection(event.target.value)}
                disabled={isStreaming}
                className="h-11 max-w-64 rounded-xl border border-input bg-card px-3 text-base text-foreground sm:text-sm"
              >
                <option value="">Select an index</option>
                {ragContainers.length > 0 && (
                  <optgroup label="Private containers">
                    {ragContainers.map((container) => (
                      <option key={container.name} value={container.name}>{container.display_name}</option>
                    ))}
                  </optgroup>
                )}
                {ragCollections.some((item) => !ragContainers.some((container) => container.name === item.name)) && (
                  <optgroup label="Existing collections">
                    {ragCollections.filter((item) => !ragContainers.some((container) => container.name === item.name)).map((item) => (
                      <option key={item.name} value={item.name}>{item.name}</option>
                    ))}
                  </optgroup>
                )}
              </select>
            </label>
          )}
          {selectedProfile?.target === "stock_research" && (
            <>
              <label className="flex flex-col gap-1 text-xs text-muted-foreground">Ticker symbol<input aria-label="Ticker symbol" value={symbol} onChange={(event) => setSymbol(event.target.value)} placeholder="e.g. AAPL" className="h-11 w-36 rounded-xl border border-input bg-card px-3 text-base sm:text-sm text-foreground" /></label>
              <label className="flex min-w-36 flex-1 flex-col gap-1 text-xs text-muted-foreground">Research context (optional)<input aria-label="Research context" value={context} onChange={(event) => setContext(event.target.value)} placeholder="Add a little context" className="h-11 w-full rounded-xl border border-input bg-card px-3 text-base sm:text-sm text-foreground" /></label>
            </>
          )}
          {selectedProfile?.target === "software_engineer" && (
            <label className="flex min-w-48 flex-1 flex-col gap-1 text-xs text-muted-foreground">Workspace path (optional)<input aria-label="Workspace path" value={workspacePath} onChange={(event) => setWorkspacePath(event.target.value)} placeholder="Workspace subpath" className="h-11 w-full rounded-xl border border-input bg-card px-3 text-base sm:text-sm text-foreground" /></label>
          )}
          {selectedProfile?.name === "document_analytics" && (
            <label className="flex min-w-48 flex-1 flex-col gap-1 text-xs text-muted-foreground">Document context (optional)<input aria-label="Document context" value={context} onChange={(event) => setContext(event.target.value)} placeholder="Add a little context" className="h-11 w-full rounded-xl border border-input bg-card px-3 text-base sm:text-sm text-foreground" /></label>
          )}
          {selectedProfile?.target === "image_generation" && (
            <label className="flex min-w-48 flex-1 flex-col gap-1 text-xs text-muted-foreground">ComfyUI workflow<textarea aria-label="ComfyUI workflow" value={workflowText} onChange={(event) => setWorkflowText(event.target.value)} placeholder="Paste exported ComfyUI API workflow JSON" rows={2} className="min-h-11 w-full rounded-xl border border-input bg-card px-3 py-2 text-base sm:text-sm text-foreground" /></label>
          )}
          {selectedProfile && <p className="w-full text-xs leading-relaxed text-muted-foreground">{selectedProfile.description}</p>}
        </div>}
        <form
          onSubmit={handleSubmit}
          className="mx-auto max-w-3xl rounded-2xl border border-input bg-card p-3 shadow-sm focus-within:border-primary/60 sm:p-4"
        >
          <label htmlFor="chat-message" className="mb-1 block px-1 text-xs font-semibold text-muted-foreground">Your message</label>
          <Textarea
            id="chat-message"
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              attachments.length > 0
                ? "Describe what to do with the attached file(s)..."
                : "Type a message... (Shift+Enter for new line)"
            }
            className="min-h-14 max-h-32 resize-none rounded-xl border-0 bg-transparent px-1 text-base shadow-none focus-visible:ring-2 focus-visible:ring-ring"
            rows={2}
            disabled={isStreaming || restoringConversation}
          />
          <div className="mt-2 flex items-center gap-2">
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-11 w-11 shrink-0 rounded-xl"
              onClick={startNewConversation}
              disabled={isStreaming || restoringConversation}
              title="New conversation"
              aria-label="New conversation"
            >
              <Plus className="h-4 w-4" />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-11 w-11 shrink-0 rounded-xl"
              onClick={() => fileInputRef.current?.click()}
              disabled={isStreaming}
              title="Attach file"
              aria-label="Attach file"
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
            <span className="hidden text-xs text-muted-foreground sm:inline">Enter to send · Shift + Enter for a new line</span>
            <Button
              type="submit"
              className="ml-auto h-11 shrink-0 rounded-xl px-4"
              aria-label={isStreaming ? "Generating response" : "Send message"}
              disabled={
                (!input.trim() && !hasReadyAttachments) ||
                isStreaming ||
                restoringConversation ||
                hasUploadingFiles
              }
            >
              {isStreaming ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Send className="h-4 w-4" />
              )}
              <span>{isStreaming ? "Thinking" : "Send"}</span>
            </Button>
          </div>
        </form>
        <div className="mx-auto mt-2 flex max-w-3xl flex-wrap items-center justify-center gap-1.5 text-center text-xs text-muted-foreground">
          <span className={isConnected ? "text-mint-ink" : "text-destructive"}>{isConnected ? "Connected" : "Disconnected"}</span><span aria-hidden="true">·</span> Responses are generated locally by Ollama
        </div>
      </div>
      {memoryDraft && (
        <Dialog open onOpenChange={(open) => { if (!open && !savingMemory) setMemoryDraft(null); }}>
          <DialogContent className="max-h-[90dvh] overflow-y-auto rounded-2xl bg-card" showCloseButton={!savingMemory} onCloseAutoFocus={(event) => { event.preventDefault(); textareaRef.current?.focus(); }}>
            <form
              onSubmit={saveMemory}
              className="space-y-4"
            >
              <div>
                <DialogTitle className="pr-6 text-xl font-bold">Remember this</DialogTitle>
                <DialogDescription className="mt-2">Review the exact text your account will save.</DialogDescription>
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
          </DialogContent>
        </Dialog>
      )}
    </div>
  );
}
