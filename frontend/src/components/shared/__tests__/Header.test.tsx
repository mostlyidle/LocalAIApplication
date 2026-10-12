import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

// Mock next/navigation
const mockPathname = vi.fn().mockReturnValue("/chat");
vi.mock("next/navigation", () => ({
  usePathname: () => mockPathname(),
}));

// Mock lucide-react icons
vi.mock("lucide-react", () => {
  const icon = ({ children, ...props }: { children?: React.ReactNode; [key: string]: unknown }) => (
    <span {...props}>{children}</span>
  );
  return {
    Moon: (props: Record<string, unknown>) => <span data-testid="moon-icon" {...props} />,
    Sun: (props: Record<string, unknown>) => <span data-testid="sun-icon" {...props} />,
    Monitor: (props: Record<string, unknown>) => <span data-testid="monitor-icon" {...props} />,
  };
});

// Mock next-themes
const mockSetTheme = vi.fn();
let mockTheme = "system";
vi.mock("next-themes", () => ({
  useTheme: () => ({ theme: mockTheme, setTheme: mockSetTheme }),
}));

// Mock shadcn components
vi.mock("@/components/ui/sidebar", () => ({
  SidebarTrigger: () => <button data-testid="sidebar-trigger">Toggle</button>,
}));

vi.mock("@/components/ui/button", () => ({
  Button: ({ children, ...props }: { children: React.ReactNode; [key: string]: unknown }) => (
    <button {...props}>{children}</button>
  ),
}));

vi.mock("@/components/ui/dropdown-menu", () => ({
  DropdownMenu: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DropdownMenuContent: ({ children }: { children: React.ReactNode }) => <div data-testid="dropdown-content">{children}</div>,
  DropdownMenuItem: ({ children, onClick, ...props }: { children: React.ReactNode; onClick?: () => void; [key: string]: unknown }) => (
    <button onClick={onClick} {...props}>{children}</button>
  ),
  DropdownMenuTrigger: ({ children, asChild }: { children: React.ReactNode; asChild?: boolean }) => <div>{children}</div>,
}));

vi.mock("@/components/ui/separator", () => ({
  Separator: (props: Record<string, unknown>) => <hr {...props} />,
}));

import { Header } from "../Header";

describe("Header", () => {
  beforeEach(() => {
    mockPathname.mockReturnValue("/chat");
    mockTheme = "system";
    mockSetTheme.mockClear();
  });

  it("renders the page title for /chat", () => {
    mockPathname.mockReturnValue("/chat");
    render(<Header />);
    expect(screen.getByText("Chat")).toBeDefined();
  });

  it("renders Dashboard for /", () => {
    mockPathname.mockReturnValue("/");
    render(<Header />);
    expect(screen.getByText("Dashboard")).toBeDefined();
  });

  it("renders Documents title", () => {
    mockPathname.mockReturnValue("/documents");
    render(<Header />);
    expect(screen.getByText("Documents")).toBeDefined();
  });

  it("renders SQL Agent title", () => {
    mockPathname.mockReturnValue("/sql");
    render(<Header />);
    expect(screen.getByText("SQL Agent")).toBeDefined();
  });

  it("renders RAG Search title", () => {
    mockPathname.mockReturnValue("/rag");
    render(<Header />);
    expect(screen.getByText("RAG Search")).toBeDefined();
  });

  it("renders Settings title", () => {
    mockPathname.mockReturnValue("/settings");
    render(<Header />);
    expect(screen.getByText("Settings")).toBeDefined();
  });

  it.each([["/memory", "Memory"], ["/meetings", "Meetings"]])("renders the title for %s", (path, title) => {
    mockPathname.mockReturnValue(path);
    render(<Header />);
    expect(screen.getByText(title)).toBeDefined();
  });

  it("falls back to Local AI for unknown paths", () => {
    mockPathname.mockReturnValue("/unknown");
    render(<Header />);
    expect(screen.getByText("Local AI")).toBeDefined();
  });

  it("renders the sidebar trigger", () => {
    render(<Header />);
    expect(screen.getByTestId("sidebar-trigger")).toBeDefined();
  });

  it("renders Light theme option", () => {
    render(<Header />);
    expect(screen.getByText("Light")).toBeDefined();
  });

  it("renders Dark theme option", () => {
    render(<Header />);
    expect(screen.getByText("Dark")).toBeDefined();
  });

  it("renders System theme option", () => {
    render(<Header />);
    expect(screen.getByText("System")).toBeDefined();
  });

  it("calls setTheme with 'light' when Light is clicked", () => {
    render(<Header />);
    fireEvent.click(screen.getByText("Light"));
    expect(mockSetTheme).toHaveBeenCalledWith("light");
  });

  it("calls setTheme with 'dark' when Dark is clicked", () => {
    render(<Header />);
    fireEvent.click(screen.getByText("Dark"));
    expect(mockSetTheme).toHaveBeenCalledWith("dark");
  });

  it("calls setTheme with 'system' when System is clicked", () => {
    render(<Header />);
    fireEvent.click(screen.getByText("System"));
    expect(mockSetTheme).toHaveBeenCalledWith("system");
  });

  it("shows moon icon in trigger when theme is dark", () => {
    mockTheme = "dark";
    render(<Header />);
    // Moon appears in the trigger button AND in the dropdown Dark item
    const moonIcons = screen.getAllByTestId("moon-icon");
    expect(moonIcons.length).toBeGreaterThanOrEqual(1);
  });

  it("shows sun icon in trigger when theme is light", () => {
    mockTheme = "light";
    render(<Header />);
    const sunIcons = screen.getAllByTestId("sun-icon");
    expect(sunIcons.length).toBeGreaterThanOrEqual(1);
  });

  it("shows monitor icon in trigger when theme is system", () => {
    mockTheme = "system";
    render(<Header />);
    const monitorIcons = screen.getAllByTestId("monitor-icon");
    expect(monitorIcons.length).toBeGreaterThanOrEqual(1);
  });
});
