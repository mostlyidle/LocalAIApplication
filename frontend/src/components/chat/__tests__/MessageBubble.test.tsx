import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MessageBubble } from "../MessageBubble";
import type { ChatMessage } from "@/types/chat";

// Mock lucide-react icons
vi.mock("lucide-react", () => ({
  ChevronDown: (props: Record<string, unknown>) => <span data-testid="chevron-down" {...props} />,
  ChevronRight: (props: Record<string, unknown>) => <span data-testid="chevron-right" {...props} />,
  Wrench: (props: Record<string, unknown>) => <span data-testid="wrench" {...props} />,
  BookmarkPlus: (props: Record<string, unknown>) => <span data-testid="bookmark-plus" {...props} />,
}));

// Mock ToolCallDisplay — must use the path as seen from the component under test
vi.mock("@/components/chat/ToolCallDisplay", () => ({
  ToolCallDisplay: ({ toolCall }: { toolCall: { toolName: string } }) => (
    <div data-testid="tool-call-display">{toolCall.toolName}</div>
  ),
}));

// Mock MarkdownContent to avoid pulling in react-markdown in tests
vi.mock("@/components/chat/MarkdownContent", () => ({
  MarkdownContent: ({ content, className }: { content: string; className?: string }) => (
    <div data-testid="markdown-content" className={className}>{content}</div>
  ),
}));

// Mock the ui components
vi.mock("@/components/ui/badge", () => ({
  Badge: ({ children, ...props }: { children: React.ReactNode }) => (
    <span data-testid="badge" {...props}>{children}</span>
  ),
}));

function makeMessage(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: "msg-1",
    role: "assistant",
    content: "Hello there",
    timestamp: "2025-01-15T10:30:00Z",
    ...overrides,
  };
}

describe("MessageBubble", () => {
  it("renders message content", () => {
    render(<MessageBubble message={makeMessage()} />);
    expect(screen.getByText("Hello there")).toBeInTheDocument();
  });

  it("renders user message aligned right", () => {
    const { container } = render(
      <MessageBubble message={makeMessage({ role: "user" })} />
    );
    const wrapper = container.firstElementChild;
    expect(wrapper?.className).toContain("justify-end");
  });

  it("lets a user review a message before saving it as memory", () => {
    const message = makeMessage({ role: "user", content: "I prefer concise answers." });
    const onRemember = vi.fn();
    render(<MessageBubble message={message} onRemember={onRemember} />);
    fireEvent.click(screen.getByRole("button", { name: "Remember this" }));
    expect(onRemember).toHaveBeenCalledWith(message);
  });

  it("renders assistant message aligned left", () => {
    const { container } = render(
      <MessageBubble message={makeMessage({ role: "assistant" })} />
    );
    const wrapper = container.firstElementChild;
    expect(wrapper?.className).toContain("justify-start");
  });

  it("shows agent badge for assistant with agentType", () => {
    render(
      <MessageBubble message={makeMessage({ agentType: "sql" })} />
    );
    expect(screen.getByText("SQL Agent")).toBeInTheDocument();
  });

  it("does not show agent badge for user messages", () => {
    render(
      <MessageBubble message={makeMessage({ role: "user", agentType: "sql" })} />
    );
    expect(screen.queryByText("SQL Agent")).not.toBeInTheDocument();
  });

  it("renders tool calls when present", () => {
    const msg = makeMessage({
      toolCalls: [
        {
          id: "tc-1",
          toolName: "execute_sql_query",
          toolInput: '{"query": "SELECT 1"}',
        },
      ],
    });
    render(<MessageBubble message={msg} />);
    expect(screen.getByTestId("tool-call-display")).toBeInTheDocument();
    expect(screen.getByText("execute_sql_query")).toBeInTheDocument();
  });

  it("lets the user open a conversation used as recalled context", () => {
    const onOpenConversation = vi.fn();
    const message = makeMessage({
      execution: {
        artifacts: {
          memory_sources: [{ conversation_id: "source-chat", title: "Kitchen plans" }],
        },
      },
    });
    render(<MessageBubble message={message} onOpenConversation={onOpenConversation} />);

    fireEvent.click(screen.getByText("Sources and task details"));
    fireEvent.click(screen.getByRole("button", { name: "Open: Kitchen plans" }));

    expect(onOpenConversation).toHaveBeenCalledWith("source-chat");
  });

  it("does not render tool calls section when empty", () => {
    render(<MessageBubble message={makeMessage({ toolCalls: [] })} />);
    expect(screen.queryByTestId("tool-call-display")).not.toBeInTheDocument();
  });

  it("renders timestamp", () => {
    render(<MessageBubble message={makeMessage()} />);
    // The timestamp rendering depends on locale, but should be present
    const timeElem = document.querySelector(".opacity-50");
    expect(timeElem).toBeInTheDocument();
  });

  it("applies primary background for user messages", () => {
    const { container } = render(
      <MessageBubble message={makeMessage({ role: "user" })} />
    );
    const bubble = container.querySelector(".bg-primary");
    expect(bubble).toBeInTheDocument();
  });

  it("applies muted background for assistant messages", () => {
    const { container } = render(
      <MessageBubble message={makeMessage({ role: "assistant" })} />
    );
    const bubble = container.querySelector(".bg-muted");
    expect(bubble).toBeInTheDocument();
  });

  it("uses agentType as fallback when no label exists", () => {
    render(
      <MessageBubble message={makeMessage({ agentType: "unknown_agent" })} />
    );
    expect(screen.getByText("unknown_agent")).toBeInTheDocument();
  });

  it("renders assistant content via MarkdownContent", () => {
    render(
      <MessageBubble message={makeMessage({ role: "assistant", content: "**bold**" })} />
    );
    expect(screen.getByTestId("markdown-content")).toBeInTheDocument();
    expect(screen.getByTestId("markdown-content")).toHaveTextContent("**bold**");
  });

  it("renders user content as plain text (no markdown)", () => {
    render(
      <MessageBubble message={makeMessage({ role: "user", content: "# heading" })} />
    );
    expect(screen.queryByTestId("markdown-content")).not.toBeInTheDocument();
    expect(screen.getByText("# heading")).toBeInTheDocument();
  });
});
