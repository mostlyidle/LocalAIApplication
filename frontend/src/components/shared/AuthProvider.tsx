"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { getCurrentAccount, login, logout } from "@/lib/api";
import type { AuthAccount } from "@/lib/api";
import { setCsrfToken } from "@/lib/auth-session";

interface AuthContextValue {
  account: AuthAccount | null;
  loading: boolean;
  error: string | null;
  signIn: (username: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue>({
  account: null,
  loading: true,
  error: null,
  signIn: async () => {},
  signOut: async () => {},
});

export function useAuth() {
  return useContext(AuthContext);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [account, setAccount] = useState<AuthAccount | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getCurrentAccount()
      .then((session) => {
        if (!active) return;
        setCsrfToken(session.csrf_token);
        setAccount(session.account);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setCsrfToken(null);
        setAccount(null);
        const statusCode = (reason as { statusCode?: number })?.statusCode;
        if (statusCode !== 401) {
          setError(reason instanceof Error ? reason.message : "Could not verify the session.");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const signIn = useCallback(async (username: string, password: string) => {
    setError(null);
    setCsrfToken(null);
    try {
      const session = await login(username, password);
      setCsrfToken(session.csrf_token);
      setAccount(session.account);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Sign in failed.");
      throw reason;
    }
  }, []);

  const signOut = useCallback(async () => {
    setError(null);
    try {
      await logout();
      setCsrfToken(null);
      setAccount(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Sign out failed.");
      throw reason;
    }
  }, []);

  return (
    <AuthContext.Provider value={{ account, loading, error, signIn, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

export function AuthenticatedShell({ children }: { children: ReactNode }) {
  const { account, loading, error, signIn } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    try {
      await signIn(username, password);
      setPassword("");
    } catch {
      // AuthProvider keeps the user-facing error.
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) {
    return <main className="grid min-h-screen place-items-center text-sm text-muted-foreground">Checking session…</main>;
  }

  if (!account) {
    return (
      <main className="grid min-h-screen place-items-center bg-muted/30 px-4">
        <form onSubmit={handleSubmit} className="w-full max-w-sm space-y-5 rounded-xl border bg-background p-6 shadow-sm">
          <div>
            <h1 className="text-xl font-semibold">Sign in to Local AI</h1>
            <p className="mt-1 text-sm text-muted-foreground">Use the account provided by your administrator.</p>
          </div>
          <label className="block space-y-1.5 text-sm font-medium">
            Username
            <input
              autoComplete="username"
              required
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              className="w-full rounded-md border bg-background px-3 py-2 font-normal"
            />
          </label>
          <label className="block space-y-1.5 text-sm font-medium">
            Password
            <input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="w-full rounded-md border bg-background px-3 py-2 font-normal"
            />
          </label>
          {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-60"
          >
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </main>
    );
  }

  return children;
}
