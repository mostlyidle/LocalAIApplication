"use client";

import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { AGENT_LABELS, AGENT_COLORS } from "@/lib/constants";
import type { ChatMessage } from "@/types/chat";
import { ToolCallDisplay } from "./ToolCallDisplay";
import { MarkdownContent } from "./MarkdownContent";
import { BookmarkPlus } from "lucide-react";
import { Button } from "@/components/ui/button";

interface MessageBubbleProps {
  message: ChatMessage;
  onRemember?: (message: ChatMessage) => void;
  canRemember?: boolean;
}

export function MessageBubble({ message, onRemember, canRemember = true }: MessageBubbleProps) {
  const isUser = message.role === "user";

  return (
    <div
      className={cn(
        "flex w-full gap-3",
        isUser ? "justify-end" : "justify-start"
      )}
    >
      <div
        className={cn(
          "max-w-[80%] rounded-lg px-4 py-3",
          isUser
            ? "bg-primary text-primary-foreground"
            : "bg-muted"
        )}
      >
        {!isUser && message.agentType && (
          <Badge
            variant="outline"
            className={cn(
              "mb-2 text-[10px]",
              AGENT_COLORS[message.agentType] ? "border-current" : ""
            )}
          >
            {AGENT_LABELS[message.agentType] ?? message.agentType}
          </Badge>
        )}
        {isUser ? (
          <div className="whitespace-pre-wrap text-sm leading-relaxed">
            {message.content}
          </div>
        ) : (
          <MarkdownContent content={message.content} className="text-sm leading-relaxed" />
        )}
        {isUser && onRemember && canRemember && (
          <Button
            type="button"
            variant="ghost"
            size="xs"
            className="mt-1 h-6 px-1 text-[10px] text-primary-foreground/80 hover:text-primary-foreground"
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
            {message.execution.limitations?.map((limitation, index) => (
              <p key={index} className="mt-2 text-muted-foreground">{limitation}</p>
            ))}
            <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-all text-[10px] text-muted-foreground">
              {JSON.stringify(message.execution.artifacts ?? {}, null, 2)}
            </pre>
          </details>
        )}
        <div className="mt-1 text-[10px] opacity-50">
          {new Date(message.timestamp).toLocaleTimeString()}
        </div>
      </div>
    </div>
  );
}
