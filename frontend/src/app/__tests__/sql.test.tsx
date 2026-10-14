import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

// Mock lucide-react
vi.mock("lucide-react", () => {
  const icon = (props: Record<string, unknown>) => <span {...props} />;
  return { Database: icon, Loader2: icon, ChevronDownIcon: icon, ChevronUpIcon: icon, CheckIcon: icon };
});

// Mock child components
vi.mock("@/components/sql/QueryEditor", () => ({
  QueryEditor: ({ onNaturalLanguageQuery, onRawSQLExecute, isLoading }: {
    onNaturalLanguageQuery: (q: string) => void;
    onRawSQLExecute: (q: string) => void;
    isLoading: boolean;
  }) => (
    <div data-testid="query-editor">
      <button data-testid="nl-query" onClick={() => onNaturalLanguageQuery("show users")}>
        NL Query
      </button>
      <button data-testid="raw-sql" onClick={() => onRawSQLExecute("SELECT 1")}>
        Raw SQL
      </button>
      {isLoading && <span data-testid="loading">Loading...</span>}
    </div>
  ),
}));

vi.mock("@/components/sql/ResultsTable", () => ({
  ResultsTable: ({ columns, rowCount }: { columns: string[]; rowCount: number }) => (
    <div data-testid="results-table">
      {rowCount} results, {columns.length} columns
    </div>
  ),
}));

vi.mock("@/components/sql/SchemaBrowser", () => ({
  SchemaBrowser: ({ database }: { database?: string }) => (
    <div data-testid="schema-browser">Schema{database ? ` (${database})` : ""}</div>
  ),
}));

const mockQuerySQL = vi.fn();
const mockExecuteSQL = vi.fn();
const mockGetSQLConnections = vi.fn();
vi.mock("@/lib/api", () => ({
  querySQL: (...args: unknown[]) => mockQuerySQL(...args),
  executeSQL: (...args: unknown[]) => mockExecuteSQL(...args),
  getSQLConnections: (...args: unknown[]) => mockGetSQLConnections(...args),
}));

import SQLPage from "@/app/sql/page";

describe("SQLPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetSQLConnections.mockResolvedValue({ connections: [] });
  });

  it("renders SQL Agent heading", () => {
    render(<SQLPage />);
    expect(screen.getByText("SQL Agent")).toBeInTheDocument();
  });

  it("renders QueryEditor and SchemaBrowser", () => {
    render(<SQLPage />);
    expect(screen.getByTestId("query-editor")).toBeInTheDocument();
    expect(screen.getByTestId("schema-browser")).toBeInTheDocument();
  });

  it("shows results after natural language query", async () => {
    mockQuerySQL.mockResolvedValue({
      results: { columns: ["id", "name"], rows: [[1, "Alice"]], row_count: 1 },
      sql: "SELECT * FROM users",
      explanation: "Shows all users",
    });
    render(<SQLPage />);
    fireEvent.click(screen.getByTestId("nl-query"));
    await waitFor(() => {
      expect(screen.getByTestId("results-table")).toBeInTheDocument();
    });
  });

  it("shows error on failed NL query", async () => {
    mockQuerySQL.mockRejectedValue(new Error("Query failed"));
    render(<SQLPage />);
    fireEvent.click(screen.getByTestId("nl-query"));
    await waitFor(() => {
      expect(screen.getByText("Query failed")).toBeInTheDocument();
    });
  });

  it("shows results after raw SQL execution", async () => {
    mockExecuteSQL.mockResolvedValue({
      columns: ["?column?"],
      rows: [[1]],
      row_count: 1,
    });
    render(<SQLPage />);
    fireEvent.click(screen.getByTestId("raw-sql"));
    await waitFor(() => {
      expect(screen.getByTestId("results-table")).toBeInTheDocument();
    });
  });

  it("shows error on failed raw SQL execution", async () => {
    mockExecuteSQL.mockRejectedValue(new Error("Execution failed"));
    render(<SQLPage />);
    fireEvent.click(screen.getByTestId("raw-sql"));
    await waitFor(() => {
      expect(screen.getByText("Execution failed")).toBeInTheDocument();
    });
  });

  it("does not show results initially", () => {
    render(<SQLPage />);
    expect(screen.queryByTestId("results-table")).not.toBeInTheDocument();
  });

  it("passes default database to SchemaBrowser", () => {
    render(<SQLPage />);
    expect(screen.getByTestId("schema-browser")).toHaveTextContent("Schema (default)");
  });

  it("shows database selector when connections are available", async () => {
    mockGetSQLConnections.mockResolvedValue({
      connections: [{ name: "demo", url: "sqlite:///demo.db" }],
    });
    render(<SQLPage />);

    await waitFor(() => {
      expect(screen.getByLabelText("Database connection")).toBeInTheDocument();
    });
  });

  it("does not show database selector when no connections", async () => {
    mockGetSQLConnections.mockResolvedValue({ connections: [] });
    render(<SQLPage />);

    // Wait for the loadConnections to resolve
    await waitFor(() => {
      expect(mockGetSQLConnections).toHaveBeenCalled();
    });

    expect(screen.queryByLabelText("Database connection")).not.toBeInTheDocument();
  });

  it("passes selected database to querySQL", async () => {
    mockGetSQLConnections.mockResolvedValue({
      connections: [{ name: "demo", url: "sqlite:///demo.db" }],
    });
    mockQuerySQL.mockResolvedValue({
      results: { columns: ["id"], rows: [[1]], row_count: 1 },
      sql: "SELECT 1",
      explanation: "ok",
    });

    render(<SQLPage />);

    await waitFor(() => {
      expect(screen.getByLabelText("Database connection")).toBeInTheDocument();
    });

    // Change to demo connection
    await userEvent.click(screen.getByRole("combobox", { name: "Database connection" }));
    await userEvent.click(await screen.findByRole("option", { name: "demo" }));

    fireEvent.click(screen.getByTestId("nl-query"));

    await waitFor(() => {
      expect(mockQuerySQL).toHaveBeenCalledWith("show users", "demo");
    });
  });
});
