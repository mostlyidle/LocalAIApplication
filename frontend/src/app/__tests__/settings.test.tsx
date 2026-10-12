import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";

// Mock lucide-react icons
vi.mock("lucide-react", () => {
  const icon = (props: Record<string, unknown>) => <span {...props} />;
  return {
    Settings: icon,
    Activity: icon,
    Database: icon,
    Brain: icon,
    Sun: icon,
    Moon: icon,
    Monitor: icon,
    CheckCircle: (props: Record<string, unknown>) => <span data-testid="check-icon" {...props} />,
    XCircle: (props: Record<string, unknown>) => <span data-testid="x-icon" {...props} />,
    Loader2: (props: Record<string, unknown>) => <span data-testid="loader" {...props} />,
    Wrench: icon,
  };
});

// Mock UI components
vi.mock("@/components/ui/button", () => ({
  Button: ({ children, ...props }: { children: React.ReactNode; [key: string]: unknown }) => (
    <button {...props}>{children}</button>
  ),
}));
vi.mock("@/components/ui/card", () => ({
  Card: ({ children }: { children: React.ReactNode }) => <div data-testid="card">{children}</div>,
  CardContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  CardDescription: ({ children }: { children: React.ReactNode }) => <p>{children}</p>,
  CardHeader: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  CardTitle: ({ children }: { children: React.ReactNode }) => <h3>{children}</h3>,
}));
vi.mock("@/components/ui/badge", () => ({
  Badge: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
}));
vi.mock("@/components/ui/separator", () => ({
  Separator: () => <hr />,
}));
vi.mock("@/components/ui/input", () => ({
  Input: (props: Record<string, unknown>) => <input {...props} />,
}));
vi.mock("@/components/ui/label", () => ({
  Label: ({ children, ...props }: { children: React.ReactNode }) => (
    <label {...props}>{children}</label>
  ),
}));

const mockSetTheme = vi.fn();
vi.mock("next-themes", () => ({
  useTheme: () => ({ theme: "system", setTheme: mockSetTheme }),
}));

const mockGetHealth = vi.fn();
const mockGetTools = vi.fn();
const mockAddSQLConnection = vi.fn();
vi.mock("@/lib/api", () => ({
  getHealth: (...args: unknown[]) => mockGetHealth(...args),
  getTools: (...args: unknown[]) => mockGetTools(...args),
  addSQLConnection: (...args: unknown[]) => mockAddSQLConnection(...args),
}));

// Dynamic import of the page (must come after mocks)
import SettingsPage from "@/app/settings/page";

describe("SettingsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetHealth.mockResolvedValue({
      status: "healthy",
      ollama: { status: "ok" },
      qdrant: { status: "ok" },
      database: { status: "ok" },
    });
    mockGetTools.mockResolvedValue({
      tools: [
        { name: "calculator_tool", description: "Calculate expressions" },
      ],
    });
  });

  it("renders Settings heading", () => {
    render(<SettingsPage />);
    expect(screen.getByText("Settings")).toBeInTheDocument();
  });

  it("shows loading state for health", () => {
    mockGetHealth.mockReturnValue(new Promise(() => {})); // never resolves
    render(<SettingsPage />);
    expect(screen.getByText("Checking services...")).toBeInTheDocument();
  });

  it("shows loading state for tools", () => {
    mockGetTools.mockReturnValue(new Promise(() => {}));
    render(<SettingsPage />);
    expect(screen.getByText("Loading tools...")).toBeInTheDocument();
  });

  it("renders service health statuses after loading", async () => {
    render(<SettingsPage />);
    await waitFor(() => {
      expect(screen.getByText("Ollama")).toBeInTheDocument();
      expect(screen.getByText("Qdrant")).toBeInTheDocument();
      expect(screen.getByText("Database")).toBeInTheDocument();
    });
  });

  it("shows error message when backend unreachable", async () => {
    mockGetHealth.mockRejectedValue(new Error("Network error"));
    render(<SettingsPage />);
    await waitFor(() => {
      expect(
        screen.getByText(/Backend is not reachable/)
      ).toBeInTheDocument();
    });
  });

  it("renders theme buttons", () => {
    render(<SettingsPage />);
    expect(screen.getByText("Light")).toBeInTheDocument();
    expect(screen.getByText("Dark")).toBeInTheDocument();
    expect(screen.getByText("System")).toBeInTheDocument();
  });

  it("calls setTheme when theme button clicked", () => {
    render(<SettingsPage />);
    fireEvent.click(screen.getByText("Dark"));
    expect(mockSetTheme).toHaveBeenCalledWith("dark");
  });

  it("renders tools after loading", async () => {
    render(<SettingsPage />);
    await waitFor(() => {
      expect(screen.getByText("calculator_tool")).toBeInTheDocument();
      expect(screen.getByText("Calculate expressions")).toBeInTheDocument();
    });
  });

  it("shows no tools message when empty", async () => {
    mockGetTools.mockResolvedValue({ tools: [] });
    render(<SettingsPage />);
    await waitFor(() => {
      expect(screen.getByText(/No tools loaded/)).toBeInTheDocument();
    });
  });

  it("renders database connection form", () => {
    render(<SettingsPage />);
    expect(screen.getByText("Database Connections")).toBeInTheDocument();
    expect(screen.getByText("Add Connection")).toBeInTheDocument();
  });

  it("disables Add Connection button when inputs empty", () => {
    render(<SettingsPage />);
    const button = screen.getByText("Add Connection");
    expect(button).toHaveAttribute("disabled");
  });
});
