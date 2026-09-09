"use client";

import { useRef, useEffect, useState, type FormEvent, type ChangeEvent } from "react";
import { Send, Plus, Loader2, Paperclip, X, Image as ImageIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Badge } from "@/components/ui/badge";
import { useChat } from "@/hooks/useChat";
import { uploadDocument } from "@/lib/api";
import { ACCEPTED_FILE_TYPES, MAX_FILE_SIZE } from "@/lib/constants";
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

export function ChatWindow() {
  const {
    messages,
    streamingContent,
    activeToolCalls,
    isConnected,
    isStreaming,
    connect,
    sendMessage,
    clearMessages,
  } = useChat();

  const [input, setInput] = useState("");
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

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
    sendMessage(message, uploadedIds);
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
            <MessageBubble key={msg.id} message={msg} />
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
        <form
          onSubmit={handleSubmit}
          className="mx-auto flex max-w-3xl items-end gap-2"
        >
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-10 w-10 shrink-0"
            onClick={clearMessages}
            disabled={isStreaming}
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
    </div>
  );
}
