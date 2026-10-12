"use client";

import { cn } from "@/lib/utils";
import { MarkdownContent } from "./MarkdownContent";
import { BrandMark } from "@/components/shared/BrandMark";

interface StreamingTextProps {
  content: string;
  className?: string;
}

export function StreamingText({ content, className }: StreamingTextProps) {
  if (!content) return null;

  return (
    <div className={cn("flex w-full justify-start gap-3", className)}>
      <BrandMark className="hidden h-10 w-10 sm:block" />
      <div className="min-w-0 max-w-[92%] rounded-2xl rounded-tl-md border bg-card px-4 py-3 shadow-xs [overflow-wrap:anywhere] sm:max-w-[85%] sm:px-5 sm:py-4">
        <MarkdownContent content={content} className="text-sm leading-relaxed" />
        <span aria-hidden="true" className="ml-0.5 inline-block h-4 w-1.5 animate-pulse rounded-full bg-primary" />
      </div>
    </div>
  );
}
