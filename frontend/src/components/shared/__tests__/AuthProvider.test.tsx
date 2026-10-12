import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("@/lib/api", () => ({
  getCurrentAccount: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
}));
vi.mock("@/lib/auth-session", () => ({ setCsrfToken: vi.fn() }));

import { AuthenticatedShell, AuthProvider, useAuth } from "../AuthProvider";
import { getCurrentAccount, login, logout } from "@/lib/api";
import { setCsrfToken } from "@/lib/auth-session";
import { ACTIVE_CONVERSATION_STORAGE_PREFIX } from "@/lib/constants";

const localStorageValues = new Map<string, string>();
Object.defineProperty(window, "localStorage", {
  configurable: true,
  value: {
    getItem: (key: string) => localStorageValues.get(key) ?? null,
    setItem: (key: string, value: string) => localStorageValues.set(key, value),
    removeItem: (key: string) => localStorageValues.delete(key),
    clear: () => localStorageValues.clear(),
  },
});

const session = {
  account: { id: "account-1", username: "alice", display_name: "Alice" },
  csrf_token: "csrf-1",
};

describe("AuthProvider", () => {
  beforeEach(() => {
    vi.mocked(getCurrentAccount).mockReset();
    vi.mocked(login).mockReset();
    vi.mocked(logout).mockReset();
    vi.mocked(setCsrfToken).mockReset();
    localStorageValues.clear();
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

  it("clears the active conversation pointer when signing out", async () => {
    vi.mocked(getCurrentAccount).mockResolvedValue(session);
    vi.mocked(logout).mockResolvedValue(undefined);
    window.localStorage.setItem(`${ACTIVE_CONVERSATION_STORAGE_PREFIX}account-1`, "conversation-1");

    function SignOutButton() {
      const { signOut } = useAuth();
      return <button onClick={() => void signOut()}>Sign out</button>;
    }

    render(<AuthProvider><SignOutButton /></AuthProvider>);
    await screen.findByRole("button", { name: "Sign out" });
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));

    await waitFor(() => expect(logout).toHaveBeenCalled());
    expect(window.localStorage.getItem(`${ACTIVE_CONVERSATION_STORAGE_PREFIX}account-1`)).toBeNull();
  });
});
