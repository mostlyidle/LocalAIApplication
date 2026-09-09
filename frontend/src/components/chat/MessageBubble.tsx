"use client";

import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { AGENT_LABELS, AGENT_COLORS } from "@/lib/constants";
import type { ChatMessage } from "@/types/chat";
import { ToolCallDisplay } from "./ToolCallDisplay";
import { MarkdownContent } from "./MarkdownContent";

interface MessageBubbleProps {
  message: ChatMessage;
}

export function MessageBubble({ message }: MessageBubbleProps) {
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
        {message.toolCalls && message.toolCalls.length > 0 && (
          <div className="mt-3 space-y-2">
            {message.toolCalls.map((tc, i) => (
              <ToolCallDisplay key={tc.id ?? i} toolCall={tc} />
            ))}
          </div>
        )}
        <div className="mt-1 text-[10px] opacity-50">
          {new Date(message.timestamp).toLocaleTimeString()}
        </div>
      </div>
    </div>
  );
}
