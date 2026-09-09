import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ResultsTable } from "../ResultsTable";

// Mock UI components
vi.mock("@/components/ui/card", () => ({
  Card: ({ children }: { children: React.ReactNode }) => <div data-testid="card">{children}</div>,
  CardContent: ({ children, ...props }: { children: React.ReactNode }) => <div {...props}>{children}</div>,
  CardHeader: ({ children, ...props }: { children: React.ReactNode }) => <div {...props}>{children}</div>,
  CardTitle: ({ children, ...props }: { children: React.ReactNode }) => <h3 {...props}>{children}</h3>,
}));
vi.mock("@/components/ui/badge", () => ({
  Badge: ({ children }: { children: React.ReactNode }) => <span data-testid="badge">{children}</span>,
}));
vi.mock("@/components/ui/scroll-area", () => ({
  ScrollArea: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));
vi.mock("@/components/ui/table", () => ({
  Table: ({ children }: { children: React.ReactNode }) => <table>{children}</table>,
  TableBody: ({ children }: { children: React.ReactNode }) => <tbody>{children}</tbody>,
  TableCell: ({ children, ...props }: { children: React.ReactNode }) => <td {...props}>{children}</td>,
  TableHead: ({ children, ...props }: { children: React.ReactNode }) => <th {...props}>{children}</th>,
  TableHeader: ({ children }: { children: React.ReactNode }) => <thead>{children}</thead>,
  TableRow: ({ children }: { children: React.ReactNode }) => <tr>{children}</tr>,
}));

describe("ResultsTable", () => {
  const defaultProps = {
    columns: ["id", "name", "age"],
    rows: [
      [1, "Alice", 30],
      [2, "Bob", 25],
    ],
    rowCount: 2,
  };

  it("renders Results title", () => {
    render(<ResultsTable {...defaultProps} />);
    expect(screen.getByText("Results")).toBeInTheDocument();
  });

  it("renders row count badge", () => {
    render(<ResultsTable {...defaultProps} />);
    expect(screen.getByText("2 rows")).toBeInTheDocument();
  });

  it("renders singular row count", () => {
    render(<ResultsTable {...defaultProps} rowCount={1} rows={[[1, "Alice", 30]]} />);
    expect(screen.getByText("1 row")).toBeInTheDocument();
  });

  it("renders column headers", () => {
    render(<ResultsTable {...defaultProps} />);
    expect(screen.getByText("id")).toBeInTheDocument();
    expect(screen.getByText("name")).toBeInTheDocument();
    expect(screen.getByText("age")).toBeInTheDocument();
  });

  it("renders cell values", () => {
    render(<ResultsTable {...defaultProps} />);
    expect(screen.getByText("Alice")).toBeInTheDocument();
    expect(screen.getByText("Bob")).toBeInTheDocument();
    expect(screen.getByText("30")).toBeInTheDocument();
  });

  it("renders NULL for null cells", () => {
    render(
      <ResultsTable
        columns={["id", "name"]}
        rows={[[1, null]]}
        rowCount={1}
      />
    );
    expect(screen.getByText("NULL")).toBeInTheDocument();
  });

  it("renders SQL when provided", () => {
    render(<ResultsTable {...defaultProps} sql="SELECT * FROM users" />);
    expect(screen.getByText("Generated SQL")).toBeInTheDocument();
    expect(screen.getByText("SELECT * FROM users")).toBeInTheDocument();
  });

  it("does not render SQL section when not provided", () => {
    render(<ResultsTable {...defaultProps} />);
    expect(screen.queryByText("Generated SQL")).not.toBeInTheDocument();
  });

  it("renders explanation when provided", () => {
    render(
      <ResultsTable {...defaultProps} explanation="This query returns all users." />
    );
    expect(screen.getByText("This query returns all users.")).toBeInTheDocument();
  });

  it("does not render explanation when not provided", () => {
    render(<ResultsTable {...defaultProps} />);
    // No explanation text should appear other than what's already expected
    expect(screen.queryByText("This query returns all users.")).not.toBeInTheDocument();
  });

  it("does not render table when columns are empty", () => {
    render(<ResultsTable columns={[]} rows={[]} rowCount={0} />);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("renders table element when columns are present", () => {
    render(<ResultsTable {...defaultProps} />);
    const table = document.querySelector("table");
    expect(table).toBeInTheDocument();
  });
});
