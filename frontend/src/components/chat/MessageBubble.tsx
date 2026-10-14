"use client";

import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { AGENT_LABELS, AGENT_COLORS } from "@/lib/constants";
import type { ChatMessage } from "@/types/chat";
import { ToolCallDisplay } from "./ToolCallDisplay";
import { MarkdownContent } from "./MarkdownContent";
import { BookmarkPlus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { BrandMark } from "@/components/shared/BrandMark";

interface MessageBubbleProps {
  message: ChatMessage;
  onRemember?: (message: ChatMessage) => void;
  canRemember?: boolean;
  onOpenConversation?: (conversationId: string) => void;
  canOpenSources?: boolean;
  agentDisplayNames?: Record<string, string>;
}

export function MessageBubble({
  message,
  onRemember,
  canRemember = true,
  onOpenConversation,
  canOpenSources = true,
  agentDisplayNames,
}: MessageBubbleProps) {
  const isUser = message.role === "user";
  const memorySources = Array.isArray(message.execution?.artifacts?.memory_sources)
    ? (message.execution.artifacts.memory_sources as Record<string, unknown>[]).filter(
        (source) =>
          source !== null &&
          typeof source === "object" &&
          typeof source.conversation_id === "string" &&
          typeof source.title === "string",
      )
    : [];

  return (
    <div
      className={cn(
        "flex w-full gap-3",
        isUser ? "justify-end" : "justify-start"
      )}
    >
      {!isUser && <BrandMark className="hidden h-10 w-10 sm:block" />}
      <div
        className={cn(
          "min-w-0 max-w-[92%] rounded-2xl px-4 py-3 [overflow-wrap:anywhere] sm:max-w-[85%] sm:px-5 sm:py-4",
          isUser
            ? "rounded-br-md bg-primary text-primary-foreground"
            : "rounded-tl-md border bg-card shadow-xs"
        )}
      >
        {!isUser && message.agentType && (
          <Badge
            variant="outline"
            className={cn(
              "mb-2 bg-violet-soft text-xs text-violet-ink",
              AGENT_COLORS[message.agentType] ? "border-current" : ""
            )}
          >
            {agentDisplayNames?.[message.agentType] ?? AGENT_LABELS[message.agentType] ?? message.agentType}
          </Badge>
        )}
        {isUser ? (
          <div className="whitespace-pre-wrap text-base leading-relaxed sm:text-sm">
            {message.content}
          </div>
        ) : (
          <MarkdownContent content={message.content} className="text-base leading-relaxed sm:text-sm" />
        )}
        {isUser && onRemember && canRemember && (
          <Button
            type="button"
            variant="ghost"
            size="xs"
            className="mt-2 min-h-9 rounded-lg px-2 text-xs text-primary-foreground hover:bg-primary-foreground/15 hover:text-primary-foreground"
            onClick={() => onRemember(message)}
          >
            <BookmarkPlus className="h-3 w-3" /> Remember this
          </Button>
        )}
        {message.toolCalls && message.toolCalls.length > 0 && (
          <div className="mt-3 space-y-2">
            {message.toolCalls.map((tc, i) => (
              <ToolCallDisplay key={tc.id ?? i} toolCall={tc} />
            ))}
          </div>
        )}
        {message.execution && (
          <details className="mt-3 rounded border border-border/60 px-2 py-1 text-xs">
            <summary className="cursor-pointer font-medium">Sources and task details</summary>
            {Array.isArray(message.execution.artifacts?.citations) && (
              <ul className="mt-2 list-disc space-y-1 pl-4">
                {(message.execution.artifacts.citations as Record<string, unknown>[]).map((citation, index) => (
                  <li key={index}>
                    {String(citation.filename ?? citation.source ?? citation.document_id ?? "Source")}
                    {citation.page != null ? `, page ${String(citation.page)}` : ""}
                    {citation.section ? ` · ${String(citation.section)}` : ""}
                  </li>
                ))}
              </ul>
            )}
            {memorySources.length > 0 && (
              <div className="mt-2">
                <p className="font-medium">Past conversations used for context</p>
                <ul className="mt-1 space-y-1">
                  {memorySources.map((source) => (
                    <li key={String(source.conversation_id)}>
                      {onOpenConversation ? (
                        <Button
                          type="button"
                          variant="link"
                          size="xs"
                          className="h-auto p-0 text-xs"
                          disabled={!canOpenSources}
                          onClick={() => onOpenConversation(String(source.conversation_id))}
                        >
                          Open: {String(source.title)}
                        </Button>
                      ) : (
                        <span>{String(source.title)}</span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {message.execution.limitations?.map((limitation, index) => (
              <p key={index} className="mt-2 text-muted-foreground">{limitation}</p>
            ))}
            <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-all text-[10px] text-muted-foreground">
              {JSON.stringify(message.execution.artifacts ?? {}, null, 2)}
            </pre>
          </details>
        )}
        <div className={cn("mt-2 text-xs", isUser ? "text-primary-foreground/75" : "text-muted-foreground")}>
          {new Date(message.timestamp).toLocaleTimeString()}
        </div>
      </div>
    </div>
  );
}
