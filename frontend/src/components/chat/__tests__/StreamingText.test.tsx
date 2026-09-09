import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { StreamingText } from "../StreamingText";

// Mock MarkdownContent to avoid pulling in react-markdown in tests
vi.mock("@/components/chat/MarkdownContent", () => ({
  MarkdownContent: ({ content, className }: { content: string; className?: string }) => (
    <div data-testid="markdown-content" className={className}>{content}</div>
  ),
}));

describe("StreamingText", () => {
  it("renders content text via MarkdownContent", () => {
    render(<StreamingText content="Hello world" />);
    expect(screen.getByTestId("markdown-content")).toHaveTextContent("Hello world");
  });

  it("returns null when content is empty", () => {
    const { container } = render(<StreamingText content="" />);
    expect(container.firstChild).toBeNull();
  });

  it("renders cursor animation element", () => {
    const { container } = render(<StreamingText content="Hello" />);
    const cursor = container.querySelector(".animate-pulse");
    expect(cursor).toBeInTheDocument();
  });

  it("applies custom className", () => {
    const { container } = render(
      <StreamingText content="test" className="custom-class" />
    );
    const wrapper = container.firstElementChild;
    expect(wrapper?.className).toContain("custom-class");
  });

  it("renders content inside MarkdownContent component", () => {
    render(<StreamingText content="**bold** text" />);
    const md = screen.getByTestId("markdown-content");
    expect(md).toBeInTheDocument();
    expect(md).toHaveTextContent("**bold** text");
  });
});
