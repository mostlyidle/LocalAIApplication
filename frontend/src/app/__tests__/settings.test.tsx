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
    Github: icon,
    Bot: icon,
    Save: icon,
    RotateCcw: icon,
    Archive: icon,
    Plus: icon,
    ChevronDownIcon: icon,
    ChevronUpIcon: icon,
    CheckIcon: icon,
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
const mockGetAgentCatalogWithArchived = vi.fn();
const mockCreateAgent = vi.fn();
const mockAddSQLConnection = vi.fn();
const mockGetGitHubConnection = vi.fn();
const mockStartGitHubConnection = vi.fn();
const mockDisconnectGitHub = vi.fn();
const mockGetGitHubRepositories = vi.fn();
const mockSetGitHubRepositorySelection = vi.fn();
vi.mock("@/lib/api", () => ({
  getHealth: (...args: unknown[]) => mockGetHealth(...args),
  getTools: (...args: unknown[]) => mockGetTools(...args),
  getAgentCatalogWithArchived: (...args: unknown[]) => mockGetAgentCatalogWithArchived(...args),
  createAgent: (...args: unknown[]) => mockCreateAgent(...args),
  addSQLConnection: (...args: unknown[]) => mockAddSQLConnection(...args),
  getGitHubConnection: (...args: unknown[]) => mockGetGitHubConnection(...args),
  startGitHubConnection: (...args: unknown[]) => mockStartGitHubConnection(...args),
  disconnectGitHub: (...args: unknown[]) => mockDisconnectGitHub(...args),
  getGitHubRepositories: (...args: unknown[]) => mockGetGitHubRepositories(...args),
  setGitHubRepositorySelection: (...args: unknown[]) => mockSetGitHubRepositorySelection(...args),
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
      services: [
        { name: "finnhub_market_data", healthy: false, message: "FINNHUB_API_KEY is not configured" },
        { name: "comfyui", healthy: true, message: "ComfyUI is reachable" },
      ],
    });
    mockGetTools.mockResolvedValue({
      tools: [
        { name: "calculator_tool", description: "Calculate expressions" },
      ],
    });
    mockGetAgentCatalogWithArchived.mockResolvedValue({ agents: [] });
    mockCreateAgent.mockResolvedValue({ agents: [] });
    mockGetGitHubConnection.mockResolvedValue({
      configured: false, connected: false, login: null, expires_at: null, install_url: null,
    });
    mockGetGitHubRepositories.mockResolvedValue({ repositories: [] });
    mockSetGitHubRepositorySelection.mockResolvedValue(undefined);
  });

  it("renders Settings heading", () => {
    render(<SettingsPage />);
    expect(screen.getByText("Settings")).toBeInTheDocument();
    expect(screen.getByText("GitHub Project Agent")).toBeInTheDocument();
  });

  it("offers the per-account GitHub setup when configured", async () => {
    mockGetGitHubConnection.mockResolvedValue({
      configured: true,
      connected: false,
      login: null,
      expires_at: null,
      install_url: "https://github.com/apps/local-ai/installations/new",
    });
    render(<SettingsPage />);
    expect(await screen.findByRole("link", { name: "Install GitHub App" })).toHaveAttribute(
      "href",
      "https://github.com/apps/local-ai/installations/new",
    );
    expect(screen.getByRole("button", { name: "Connect GitHub" })).toBeEnabled();
  });

  it("shows account repositories and persists the agent allowlist selection", async () => {
    mockGetGitHubConnection.mockResolvedValue({
      configured: true, connected: true, login: "octocat", expires_at: null, install_url: null,
    });
    mockGetGitHubRepositories.mockResolvedValue({ repositories: [{
      repository_id: "42",
      full_name: "octocat/hello-world",
      html_url: "https://github.com/octocat/hello-world",
      default_branch: "main",
      is_private: true,
      selected: false,
    }] });
    render(<SettingsPage />);
    const checkbox = await screen.findByRole("checkbox", { name: "Allow agent to use octocat/hello-world" });
    expect(checkbox).not.toBeChecked();
    fireEvent.click(checkbox);
    await waitFor(() => expect(mockSetGitHubRepositorySelection).toHaveBeenCalledWith("42", true));
    await waitFor(() => expect(checkbox).toBeChecked());
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
      expect(screen.getByText("Finnhub Market Data")).toBeInTheDocument();
      expect(screen.getByText("ComfyUI")).toBeInTheDocument();
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

  it("does not let a profile refresh overwrite an edited prompt", async () => {
    const agent = {
      name: "chat",
      display_name: "Chat",
      target: "chat",
      description: "General chat",
      default_for_target: true,
      system_prompt: "Original prompt",
      inference: {
        allowed_models: ["llama3.1:8b"],
        defaults: { model: "llama3.1:8b", temperature: 0.1 },
        limits: { temperature: { minimum: 0, maximum: 2 } },
      },
    };
    mockGetAgentCatalogWithArchived.mockResolvedValue({ agents: [agent] });
    render(<SettingsPage />);
    const textarea = await screen.findByDisplayValue("Original prompt");
    await waitFor(() => expect(mockGetAgentCatalogWithArchived).toHaveBeenCalledTimes(1));

    fireEvent.change(textarea, { target: { value: "Unsaved draft" } });

    expect(textarea).toHaveValue("Unsaved draft");
  });

  it("renders database connection form", () => {
    render(<SettingsPage />);
    expect(screen.getByText("Database Connections")).toBeInTheDocument();
    expect(screen.getByText("Add Connection")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("sqlite+aiosqlite:///path/to/db.sqlite")).toBeInTheDocument();
  });

  it("trims the name sent for a new specialist and selects the created profile", async () => {
    const baseAgent = {
      name: "chat",
      display_name: "Chat",
      target: "chat",
      description: "General chat",
      default_for_target: true,
      system_prompt: "Base prompt",
      inference: {
        allowed_models: ["llama3.1:8b"],
        defaults: { model: "llama3.1:8b", temperature: 0.1 },
        limits: { temperature: { minimum: 0, maximum: 2 } },
      },
    };
    const customAgent = {
      ...baseAgent,
      name: "research-helper",
      display_name: "Research helper",
      description: "Research notes",
      system_prompt: "Custom prompt",
      is_custom: true,
      default_for_target: false,
    };
    mockGetAgentCatalogWithArchived.mockResolvedValue({ agents: [baseAgent] });
    mockCreateAgent.mockResolvedValue({ agents: [baseAgent, customAgent] });
    render(<SettingsPage />);

    fireEvent.change(await screen.findByLabelText("Name"), { target: { value: "  Research helper  " } });
    fireEvent.change(screen.getByLabelText("Description"), { target: { value: "Research notes" } });
    fireEvent.click(screen.getByRole("button", { name: "Create agent" }));

    await waitFor(() => expect(mockCreateAgent).toHaveBeenCalledWith({
      source_agent: "chat",
      display_name: "Research helper",
      description: "Research notes",
    }));
    expect(await screen.findByDisplayValue("Custom prompt")).toBeInTheDocument();
  });

  it("disables Add Connection button when inputs empty", () => {
    render(<SettingsPage />);
    const button = screen.getByText("Add Connection");
    expect(button).toHaveAttribute("disabled");
  });
});
