import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryEditor } from "../QueryEditor";

// ---------------------------------------------------------------------------
// Props factory
// ---------------------------------------------------------------------------

function defaultProps() {
  return {
    onNaturalLanguageQuery: vi.fn().mockResolvedValue(undefined),
    onRawSQLExecute: vi.fn().mockResolvedValue(undefined),
    isLoading: false,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("QueryEditor", () => {
  it("renders Natural Language and Raw SQL tabs", () => {
    render(<QueryEditor {...defaultProps()} />);

    expect(screen.getByText("Natural Language")).toBeInTheDocument();
    expect(screen.getByText("Raw SQL")).toBeInTheDocument();
  });

  it("renders the Ask AI button in natural language tab", () => {
    render(<QueryEditor {...defaultProps()} />);

    expect(screen.getByText("Ask AI")).toBeInTheDocument();
  });

  it("submits natural language query", async () => {
    const props = defaultProps();
    const user = userEvent.setup();
    render(<QueryEditor {...props} />);

    const textarea = screen.getByRole("textbox", { name: "Question for the SQL agent" });
    await user.type(textarea, "Show me all orders");

    const form = textarea.closest("form")!;
    fireEvent.submit(form);

    expect(props.onNaturalLanguageQuery).toHaveBeenCalledWith("Show me all orders");
  });

  it("does not submit empty natural language query", () => {
    const props = defaultProps();
    render(<QueryEditor {...props} />);

    const textarea = screen.getByRole("textbox", { name: "Question for the SQL agent" });
    const form = textarea.closest("form")!;
    fireEvent.submit(form);

    expect(props.onNaturalLanguageQuery).not.toHaveBeenCalled();
  });

  it("switches to Raw SQL tab and submits", async () => {
    const props = defaultProps();
    const user = userEvent.setup();
    render(<QueryEditor {...props} />);

    // Click on the Raw SQL tab
    const sqlTab = screen.getByText("Raw SQL");
    await user.click(sqlTab);

    const textarea = screen.getByRole("textbox", { name: "SQL query" });
    await user.type(textarea, "SELECT 1");

    const form = textarea.closest("form")!;
    fireEvent.submit(form);

    expect(props.onRawSQLExecute).toHaveBeenCalledWith("SELECT 1");
  });

  it("does not submit empty raw SQL", async () => {
    const props = defaultProps();
    const user = userEvent.setup();
    render(<QueryEditor {...props} />);

    const sqlTab = screen.getByText("Raw SQL");
    await user.click(sqlTab);

    const textarea = screen.getByRole("textbox", { name: "SQL query" });
    const form = textarea.closest("form")!;
    fireEvent.submit(form);

    expect(props.onRawSQLExecute).not.toHaveBeenCalled();
  });

  it("disables Ask AI button when isLoading is true", () => {
    render(<QueryEditor {...defaultProps()} isLoading={true} />);

    const askButton = screen.getByText("Ask AI").closest("button")!;
    expect(askButton).toBeDisabled();
  });

  it("disables Execute button when isLoading is true", async () => {
    const user = userEvent.setup();
    render(<QueryEditor {...defaultProps()} isLoading={true} />);

    const sqlTab = screen.getByText("Raw SQL");
    await user.click(sqlTab);

    const executeButton = screen.getByText("Execute").closest("button")!;
    expect(executeButton).toBeDisabled();
  });

  it("disables Ask AI button when textarea is empty", () => {
    render(<QueryEditor {...defaultProps()} />);

    const askButton = screen.getByText("Ask AI").closest("button")!;
    expect(askButton).toBeDisabled();
  });

  it("enables Ask AI button when textarea has content", async () => {
    const user = userEvent.setup();
    render(<QueryEditor {...defaultProps()} />);

    const textarea = screen.getByRole("textbox", { name: "Question for the SQL agent" });
    await user.type(textarea, "test");

    const askButton = screen.getByText("Ask AI").closest("button")!;
    expect(askButton).not.toBeDisabled();
  });
});
