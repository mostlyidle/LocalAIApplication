import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

// Mock next/link
vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string; [key: string]: unknown }) => (
    <a href={href} {...props}>{children}</a>
  ),
}));

// Mock next/navigation
const mockPathname = vi.fn().mockReturnValue("/chat");
const mockSetOpenMobile = vi.fn();
let mockIsMobile = false;
vi.mock("next/navigation", () => ({
  usePathname: () => mockPathname(),
}));

// Mock lucide-react icons
vi.mock("lucide-react", () => {
  const icon = ({ children, ...props }: { children?: React.ReactNode; [key: string]: unknown }) => (
    <span {...props}>{children}</span>
  );
  return {
    MessageSquare: icon,
    FileText: icon,
    Database: icon,
    Search: icon,
    Settings: icon,
    Brain: icon,
    BrainCircuit: icon,
    Activity: icon,
  };
});

// Mock shadcn sidebar components
vi.mock("@/components/ui/sidebar", () => ({
  useSidebar: () => ({ isMobile: mockIsMobile, setOpenMobile: mockSetOpenMobile }),
  SidebarTrigger: () => <button>Toggle Sidebar</button>,
  Sidebar: ({ children, ...props }: { children: React.ReactNode }) => <nav {...props}>{children}</nav>,
  SidebarContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SidebarGroup: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SidebarGroupContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SidebarGroupLabel: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
  SidebarHeader: ({ children, ...props }: { children: React.ReactNode }) => <div {...props}>{children}</div>,
  SidebarMenu: ({ children }: { children: React.ReactNode }) => <ul>{children}</ul>,
  SidebarMenuButton: ({ children, isActive, asChild, ...props }: { children: React.ReactNode; isActive?: boolean; asChild?: boolean; [key: string]: unknown }) => (
    <div data-active={isActive} {...props}>{children}</div>
  ),
  SidebarMenuItem: ({ children }: { children: React.ReactNode }) => <li>{children}</li>,
  SidebarFooter: ({ children, ...props }: { children: React.ReactNode }) => <div {...props}>{children}</div>,
}));

// Mock shadcn badge
vi.mock("@/components/ui/badge", () => ({
  Badge: ({ children, ...props }: { children: React.ReactNode }) => <span {...props}>{children}</span>,
}));

import { AppSidebar } from "../AppSidebar";

describe("AppSidebar", () => {
  beforeEach(() => {
    mockPathname.mockReturnValue("/chat");
    mockIsMobile = false;
    mockSetOpenMobile.mockClear();
  });

  it("renders the Local AI brand title", () => {
    render(<AppSidebar />);
    expect(screen.getByText("Local AI")).toBeDefined();
  });

  it("closes the mobile drawer after selecting a page", () => {
    mockIsMobile = true;
    render(<AppSidebar />);
    fireEvent.click(screen.getByRole("link", { name: "Documents" }));
    expect(mockSetOpenMobile).toHaveBeenCalledWith(false);
  });

  it("renders the subtitle", () => {
    render(<AppSidebar />);
    expect(screen.getByText("Fully Local Intelligence")).toBeDefined();
  });

  it("renders all navigation items", () => {
    render(<AppSidebar />);
    expect(screen.getByText("Chat")).toBeDefined();
    expect(screen.getByText("Documents")).toBeDefined();
    expect(screen.getByText("SQL Agent")).toBeDefined();
    expect(screen.getByText("RAG Search")).toBeDefined();
    expect(screen.getByText("Memory")).toBeDefined();
    expect(screen.getByText("Settings")).toBeDefined();
  });

  it("renders navigation links with correct hrefs", () => {
    render(<AppSidebar />);
    const links = screen.getAllByRole("link");
    const hrefs = links.map((l) => l.getAttribute("href"));
    expect(hrefs).toContain("/");
    expect(hrefs).toContain("/chat");
    expect(hrefs).toContain("/documents");
    expect(hrefs).toContain("/sql");
    expect(hrefs).toContain("/rag");
    expect(hrefs).toContain("/memory");
    expect(hrefs).toContain("/settings");
  });

  it("marks the current path as active", () => {
    mockPathname.mockReturnValue("/chat");
    render(<AppSidebar />);
    // Find the menu button wrapping the Chat link
    const chatLink = screen.getByText("Chat").closest("[data-active]");
    expect(chatLink?.getAttribute("data-active")).toBe("true");
  });

  it("marks sub-paths as active", () => {
    mockPathname.mockReturnValue("/documents/123");
    render(<AppSidebar />);
    const docsLink = screen.getByText("Documents").closest("[data-active]");
    expect(docsLink?.getAttribute("data-active")).toBe("true");
  });

  it("does not mark non-matching paths as active", () => {
    mockPathname.mockReturnValue("/chat");
    render(<AppSidebar />);
    const sqlLink = screen.getByText("SQL Agent").closest("[data-active]");
    expect(sqlLink?.getAttribute("data-active")).toBe("false");
  });

  it("renders the footer with Ollama text", () => {
    render(<AppSidebar />);
    expect(screen.getByText("Powered by Ollama")).toBeDefined();
  });

  it("renders the Local badge in the footer", () => {
    render(<AppSidebar />);
    expect(screen.getByText("Local")).toBeDefined();
  });

  it("renders the Navigation group label", () => {
    render(<AppSidebar />);
    expect(screen.getByText("Navigation")).toBeDefined();
  });
});
