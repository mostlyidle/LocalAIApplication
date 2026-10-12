import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("@/lib/api", () => ({
  getCurrentAccount: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
}));
vi.mock("@/lib/auth-session", () => ({ setCsrfToken: vi.fn() }));

import { AuthenticatedShell, AuthProvider } from "../AuthProvider";
import { getCurrentAccount, login } from "@/lib/api";
import { setCsrfToken } from "@/lib/auth-session";

const session = {
  account: { id: "account-1", username: "alice", display_name: "Alice" },
  csrf_token: "csrf-1",
};

describe("AuthProvider", () => {
  beforeEach(() => {
    vi.mocked(getCurrentAccount).mockReset();
    vi.mocked(login).mockReset();
    vi.mocked(setCsrfToken).mockReset();
  });

  it("shows sign in while unauthenticated and opens the app after login", async () => {
    vi.mocked(getCurrentAccount).mockRejectedValue(Object.assign(new Error("Unauthorized"), { statusCode: 401 }));
    vi.mocked(login).mockResolvedValue(session);

    render(
      <AuthProvider>
        <AuthenticatedShell><div>Protected application</div></AuthenticatedShell>
      </AuthProvider>,
    );

    await screen.findByText("Sign in to Local AI");
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "alice" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByText("Protected application")).toBeTruthy();
    expect(login).toHaveBeenCalledWith("alice", "secret");
    expect(setCsrfToken).toHaveBeenCalledWith("csrf-1");
  });

  it("reports a session verification failure", async () => {
    vi.mocked(getCurrentAccount).mockRejectedValue(new Error("Backend unavailable"));

    render(
      <AuthProvider>
        <AuthenticatedShell><div>Protected application</div></AuthenticatedShell>
      </AuthProvider>,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("Backend unavailable");
    await waitFor(() => expect(screen.queryByText("Protected application")).toBeNull());
  });
});
