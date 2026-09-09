"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, Wrench } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { ToolCall } from "@/types/chat";

interface ToolCallDisplayProps {
  toolCall: Partial<ToolCall>;
}

export function ToolCallDisplay({ toolCall }: ToolCallDisplayProps) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="rounded-md border bg-background/50 text-xs">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-accent/50"
      >
        {expanded ? (
          <ChevronDown className="h-3 w-3" />
        ) : (
          <ChevronRight className="h-3 w-3" />
        )}
        <Wrench className="h-3 w-3 text-muted-foreground" />
        <span className="font-mono font-medium">{toolCall.toolName}</span>
        {toolCall.durationMs && (
          <Badge variant="secondary" className="ml-auto text-[10px]">
            {toolCall.durationMs.toFixed(0)}ms
          </Badge>
        )}
      </button>
      {expanded && (
        <div className="space-y-2 border-t px-3 py-2">
          <div>
            <div className="mb-1 font-medium text-muted-foreground">Input</div>
            <pre className="overflow-x-auto rounded bg-muted p-2 text-[11px]">
              {toolCall.toolInput
                ? (() => {
                    try {
                      return JSON.stringify(JSON.parse(toolCall.toolInput), null, 2);
                    } catch {
                      return toolCall.toolInput;
                    }
                  })()
                : "{}"}
            </pre>
          </div>
          {toolCall.toolOutput && (
            <div>
              <div className="mb-1 font-medium text-muted-foreground">Output</div>
              <pre className="max-h-48 overflow-auto rounded bg-muted p-2 text-[11px]">
                {toolCall.toolOutput}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
