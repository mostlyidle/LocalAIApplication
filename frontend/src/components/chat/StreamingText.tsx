"use client";

import { cn } from "@/lib/utils";
import { MarkdownContent } from "./MarkdownContent";

interface StreamingTextProps {
  content: string;
  className?: string;
}

export function StreamingText({ content, className }: StreamingTextProps) {
  if (!content) return null;

  return (
    <div className={cn("flex w-full justify-start", className)}>
      <div className="max-w-[80%] rounded-lg bg-muted px-4 py-3">
        <MarkdownContent content={content} className="text-sm leading-relaxed" />
        <span className="ml-0.5 inline-block h-4 w-1.5 animate-pulse bg-foreground/70" />
      </div>
    </div>
  );
}
