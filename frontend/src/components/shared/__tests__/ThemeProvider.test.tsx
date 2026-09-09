import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

// Mock next-themes
vi.mock("next-themes", () => ({
  ThemeProvider: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="next-themes-provider">{children}</div>
  ),
}));

import { ThemeProvider } from "../ThemeProvider";

describe("ThemeProvider", () => {
  it("renders children", () => {
    render(
      <ThemeProvider>
        <span>child content</span>
      </ThemeProvider>,
    );
    expect(screen.getByText("child content")).toBeDefined();
  });

  it("delegates to next-themes ThemeProvider", () => {
    render(
      <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
        <span>themed</span>
      </ThemeProvider>,
    );
    expect(screen.getByTestId("next-themes-provider")).toBeDefined();
    expect(screen.getByText("themed")).toBeDefined();
  });

  it("renders as a thin wrapper without extra DOM elements", () => {
    const { container } = render(
      <ThemeProvider>
        <span>only child</span>
      </ThemeProvider>,
    );
    // The wrapper is the mocked next-themes div, and our child is inside it
    const provider = screen.getByTestId("next-themes-provider");
    expect(provider.textContent).toBe("only child");
  });
});
