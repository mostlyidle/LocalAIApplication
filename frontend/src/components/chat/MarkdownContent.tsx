"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import { oneDark } from "react-syntax-highlighter/dist/esm/styles/prism";
import { cn } from "@/lib/utils";
import type { ComponentPropsWithoutRef } from "react";

interface MarkdownContentProps {
  content: string;
  className?: string;
}

/**
 * Renders markdown content with GFM support and syntax-highlighted code blocks.
 *
 * Used by both MessageBubble (completed messages) and StreamingText (in-progress).
 * Design: uses react-markdown + remark-gfm for tables/strikethrough/task-lists,
 * and react-syntax-highlighter with the oneDark theme for fenced code blocks.
 */
export function MarkdownContent({ content, className }: MarkdownContentProps) {
  return (
    <div className={cn("max-w-none break-words [&_p+p]:mt-3 [&_ul]:my-3 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:my-3 [&_ol]:list-decimal [&_ol]:pl-5 [&_li]:my-1 [&_h1]:my-3 [&_h1]:text-xl [&_h2]:my-3 [&_h2]:text-lg [&_h3]:my-3 [&_h3]:font-semibold [&_a]:text-primary [&_a]:underline [&_blockquote]:my-3 [&_blockquote]:border-l-2 [&_blockquote]:border-primary/40 [&_blockquote]:pl-3 [&_pre]:my-3", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code({ className: codeClassName, children, ...rest }) {
            const match = /language-(\w+)/.exec(codeClassName || "");
            const codeString = String(children).replace(/\n$/, "");

            // Inline code (no language class, single-line content without newlines)
            if (!match) {
              return (
                <code
                  className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs"
                  {...rest}
                >
                  {children}
                </code>
              );
            }

            // Fenced code block with syntax highlighting
            return (
              <SyntaxHighlighter
                style={oneDark}
                language={match[1]}
                PreTag="div"
                customStyle={{
                  margin: 0,
                  borderRadius: "0.375rem",
                  fontSize: "0.75rem",
                }}
              >
                {codeString}
              </SyntaxHighlighter>
            );
          },
          // Tighten up table styling
          table({ children, ...rest }: ComponentPropsWithoutRef<"table">) {
            return (
              <div className="overflow-x-auto">
                <table className="text-xs" {...rest}>
                  {children}
                </table>
              </div>
            );
          },
          // Ensure links open in new tabs
          a({ children, href, ...rest }: ComponentPropsWithoutRef<"a">) {
            return (
              <a href={href} target="_blank" rel="noopener noreferrer" {...rest}>
                {children}
              </a>
            );
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
