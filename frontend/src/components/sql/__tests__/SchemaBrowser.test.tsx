import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { SchemaBrowser } from "../SchemaBrowser";

// Mock lucide-react icons
vi.mock("lucide-react", () => ({
  Database: (props: Record<string, unknown>) => <span data-testid="database-icon" {...props} />,
  Table2: (props: Record<string, unknown>) => <span data-testid="table-icon" {...props} />,
  Key: (props: Record<string, unknown>) => <span data-testid="key-icon" {...props} />,
  Loader2: (props: Record<string, unknown>) => <span data-testid="loader-icon" {...props} />,
  ChevronRight: (props: Record<string, unknown>) => <span data-testid="chevron-right" {...props} />,
  ChevronDown: (props: Record<string, unknown>) => <span data-testid="chevron-down" {...props} />,
}));

// Mock UI components
vi.mock("@/components/ui/card", () => ({
  Card: ({ children }: { children: React.ReactNode }) => <div data-testid="card">{children}</div>,
  CardContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  CardHeader: ({ children, ...props }: { children: React.ReactNode }) => <div {...props}>{children}</div>,
  CardTitle: ({ children, ...props }: { children: React.ReactNode }) => <h3 {...props}>{children}</h3>,
}));
vi.mock("@/components/ui/badge", () => ({
  Badge: ({ children }: { children: React.ReactNode }) => <span data-testid="badge">{children}</span>,
}));
vi.mock("@/components/ui/scroll-area", () => ({
  ScrollArea: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

const mockGetSQLSchema = vi.fn();
vi.mock("@/lib/api", () => ({
  getSQLSchema: (...args: unknown[]) => mockGetSQLSchema(...args),
}));

const sampleSchema = {
  tables: [
    {
      name: "users",
      columns: [
        { name: "id", type: "INTEGER", nullable: false, primary_key: true },
        { name: "name", type: "TEXT", nullable: false, primary_key: false },
        { name: "email", type: "TEXT", nullable: true, primary_key: false },
      ],
    },
    {
      name: "orders",
      columns: [
        { name: "id", type: "INTEGER", nullable: false, primary_key: true },
        { name: "user_id", type: "INTEGER", nullable: false, primary_key: false },
      ],
    },
  ],
};

describe("SchemaBrowser", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows loading state initially", () => {
    mockGetSQLSchema.mockReturnValue(new Promise(() => {})); // never resolves
    render(<SchemaBrowser />);
    expect(screen.getByText("Loading schema...")).toBeInTheDocument();
  });

  it("renders table names after loading", async () => {
    mockGetSQLSchema.mockResolvedValue(sampleSchema);
    render(<SchemaBrowser />);
    await waitFor(() => {
      expect(screen.getByText("users")).toBeInTheDocument();
      expect(screen.getByText("orders")).toBeInTheDocument();
    });
  });

  it("explains when a database has no tables", async () => {
    mockGetSQLSchema.mockResolvedValue({ tables: [] });
    render(<SchemaBrowser />);

    expect(await screen.findByText(/No tables found in this database/)).toBeInTheDocument();
  });

  it("shows column count badges", async () => {
    mockGetSQLSchema.mockResolvedValue(sampleSchema);
    render(<SchemaBrowser />);
    await waitFor(() => {
      expect(screen.getByText("3 cols")).toBeInTheDocument();
      expect(screen.getByText("2 cols")).toBeInTheDocument();
    });
  });

  it("shows error message on fetch failure", async () => {
    mockGetSQLSchema.mockRejectedValue(new Error("Network error"));
    render(<SchemaBrowser />);
    await waitFor(() => {
      expect(screen.getByText("Network error")).toBeInTheDocument();
    });
  });

  it("expands table to show columns on click", async () => {
    mockGetSQLSchema.mockResolvedValue(sampleSchema);
    render(<SchemaBrowser />);
    await waitFor(() => {
      expect(screen.getByText("users")).toBeInTheDocument();
    });

    // Click to expand users table
    const buttons = screen.getAllByRole("button");
    const usersBtn = buttons.find(
      (btn) => btn.textContent?.includes("users")
    );
    expect(usersBtn).toBeDefined();
    fireEvent.click(usersBtn!);

    // Should show column names
    expect(screen.getByText("id")).toBeInTheDocument();
    expect(screen.getByText("name")).toBeInTheDocument();
    expect(screen.getByText("email")).toBeInTheDocument();
  });

  it("shows column type info when expanded", async () => {
    mockGetSQLSchema.mockResolvedValue(sampleSchema);
    render(<SchemaBrowser />);
    await waitFor(() => {
      expect(screen.getByText("users")).toBeInTheDocument();
    });

    const buttons = screen.getAllByRole("button");
    const usersBtn = buttons.find(
      (btn) => btn.textContent?.includes("users")
    );
    fireEvent.click(usersBtn!);

    expect(screen.getByText("INTEGER")).toBeInTheDocument();
    // Multiple TEXT columns exist (name and email)
    expect(screen.getAllByText("TEXT").length).toBeGreaterThanOrEqual(1);
  });

  it("shows nullable indicator for nullable columns", async () => {
    mockGetSQLSchema.mockResolvedValue(sampleSchema);
    render(<SchemaBrowser />);
    await waitFor(() => {
      expect(screen.getByText("users")).toBeInTheDocument();
    });

    const buttons = screen.getAllByRole("button");
    const usersBtn = buttons.find(
      (btn) => btn.textContent?.includes("users")
    );
    fireEvent.click(usersBtn!);

    expect(screen.getByText("nullable")).toBeInTheDocument();
  });

  it("collapses table on second click", async () => {
    mockGetSQLSchema.mockResolvedValue(sampleSchema);
    render(<SchemaBrowser />);
    await waitFor(() => {
      expect(screen.getByText("users")).toBeInTheDocument();
    });

    const buttons = screen.getAllByRole("button");
    const usersBtn = buttons.find(
      (btn) => btn.textContent?.includes("users")
    );
    fireEvent.click(usersBtn!); // expand
    expect(screen.getByText("id")).toBeInTheDocument();
    fireEvent.click(usersBtn!); // collapse
    // Columns should no longer be visible (except "id" might match something else)
    expect(screen.queryByText("nullable")).not.toBeInTheDocument();
  });

  it("renders Schema title", async () => {
    mockGetSQLSchema.mockResolvedValue(sampleSchema);
    render(<SchemaBrowser />);
    expect(screen.getByText("Schema")).toBeInTheDocument();
  });

  it("handles empty tables array", async () => {
    mockGetSQLSchema.mockResolvedValue({ tables: [] });
    render(<SchemaBrowser />);
    await waitFor(() => {
      expect(screen.queryByText("Loading schema...")).not.toBeInTheDocument();
    });
    // No table buttons should exist
    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });

  it("ignores schema responses from a previously selected database", async () => {
    let resolveFirst!: (schema: typeof sampleSchema) => void;
    mockGetSQLSchema.mockImplementation((database: string) => database === "first"
      ? new Promise((resolve) => { resolveFirst = resolve; })
      : Promise.resolve({ tables: [{ name: "current_db", columns: [] }] }));
    const { rerender } = render(<SchemaBrowser database="first" />);
    await waitFor(() => expect(mockGetSQLSchema).toHaveBeenCalledWith("first"));

    rerender(<SchemaBrowser database="second" />);
    expect(await screen.findByText("current_db")).toBeInTheDocument();
    resolveFirst({ tables: [{ name: "stale_db", columns: [] }] });

    await waitFor(() => expect(screen.queryByText("stale_db")).not.toBeInTheDocument());
    expect(screen.getByText("current_db")).toBeInTheDocument();
  });
});
