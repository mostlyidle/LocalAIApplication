import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { ToolCallDisplay } from "../ToolCallDisplay";
import type { ToolCall } from "@/types/chat";

// Mock lucide-react icons
vi.mock("lucide-react", () => ({
  ChevronDown: (props: Record<string, unknown>) => <span data-testid="chevron-down" {...props} />,
  ChevronRight: (props: Record<string, unknown>) => <span data-testid="chevron-right" {...props} />,
  Wrench: (props: Record<string, unknown>) => <span data-testid="wrench" {...props} />,
}));

// Mock the ui components
vi.mock("@/components/ui/badge", () => ({
  Badge: ({ children, ...props }: { children: React.ReactNode }) => (
    <span data-testid="badge" {...props}>{children}</span>
  ),
}));

function makeToolCall(overrides: Partial<ToolCall> = {}): Partial<ToolCall> {
  return {
    id: "tc-1",
    toolName: "execute_sql_query",
    toolInput: '{"query": "SELECT 1"}',
    ...overrides,
  };
}

describe("ToolCallDisplay", () => {
  it("renders tool name", () => {
    render(<ToolCallDisplay toolCall={makeToolCall()} />);
    expect(screen.getByText("execute_sql_query")).toBeInTheDocument();
  });

  it("starts collapsed by default", () => {
    render(<ToolCallDisplay toolCall={makeToolCall()} />);
    expect(screen.queryByText("Input")).not.toBeInTheDocument();
    expect(screen.getByTestId("chevron-right")).toBeInTheDocument();
  });

  it("expands on click to show input", () => {
    render(<ToolCallDisplay toolCall={makeToolCall()} />);
    const button = screen.getByRole("button");
    fireEvent.click(button);
    expect(screen.getByText("Input")).toBeInTheDocument();
    expect(screen.getByTestId("chevron-down")).toBeInTheDocument();
  });

  it("displays tool input as formatted JSON when expanded", () => {
    render(
      <ToolCallDisplay
        toolCall={makeToolCall({ toolInput: '{"query":"SELECT 1"}' })}
      />
    );
    fireEvent.click(screen.getByRole("button"));
    // JSON.stringify(JSON.parse(...), null, 2) should produce formatted output
    expect(screen.getByText(/SELECT 1/)).toBeInTheDocument();
  });

  it("shows duration badge when durationMs is provided", () => {
    render(
      <ToolCallDisplay toolCall={makeToolCall({ durationMs: 123.456 })} />
    );
    expect(screen.getByText("123ms")).toBeInTheDocument();
  });

  it("does not show duration badge when durationMs is undefined", () => {
    render(
      <ToolCallDisplay toolCall={makeToolCall({ durationMs: undefined })} />
    );
    expect(screen.queryByTestId("badge")).not.toBeInTheDocument();
  });

  it("shows output section when toolOutput is provided and expanded", () => {
    render(
      <ToolCallDisplay
        toolCall={makeToolCall({ toolOutput: "3 rows returned" })}
      />
    );
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByText("Output")).toBeInTheDocument();
    expect(screen.getByText("3 rows returned")).toBeInTheDocument();
  });

  it("does not show output section when toolOutput is undefined", () => {
    render(
      <ToolCallDisplay toolCall={makeToolCall({ toolOutput: undefined })} />
    );
    fireEvent.click(screen.getByRole("button"));
    expect(screen.queryByText("Output")).not.toBeInTheDocument();
  });

  it("collapses back on second click", () => {
    render(<ToolCallDisplay toolCall={makeToolCall()} />);
    const button = screen.getByRole("button");
    fireEvent.click(button); // expand
    expect(screen.getByText("Input")).toBeInTheDocument();
    fireEvent.click(button); // collapse
    expect(screen.queryByText("Input")).not.toBeInTheDocument();
  });

  it("shows empty object when toolInput is undefined", () => {
    render(
      <ToolCallDisplay toolCall={makeToolCall({ toolInput: undefined })} />
    );
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByText("{}")).toBeInTheDocument();
  });

  it("handles malformed JSON in toolInput without crashing", () => {
    render(
      <ToolCallDisplay
        toolCall={makeToolCall({ toolInput: "not valid json {{{" })}
      />
    );
    fireEvent.click(screen.getByRole("button"));
    // Should fall back to showing the raw string
    expect(screen.getByText("not valid json {{{")).toBeInTheDocument();
  });

  it("handles toolInput that is plain text without crashing", () => {
    render(
      <ToolCallDisplay
        toolCall={makeToolCall({ toolInput: "SELECT * FROM users" })}
      />
    );
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByText("SELECT * FROM users")).toBeInTheDocument();
  });
});
