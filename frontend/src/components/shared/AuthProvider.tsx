"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import { getCurrentAccount, login, logout } from "@/lib/api";
import type { AuthAccount } from "@/lib/api";
import { setCsrfToken } from "@/lib/auth-session";
import { ACTIVE_CONVERSATION_STORAGE_PREFIX } from "@/lib/constants";
import { BrandMark } from "./BrandMark";

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
      if (account && typeof window !== "undefined") {
        window.localStorage.removeItem(`${ACTIVE_CONVERSATION_STORAGE_PREFIX}${account.id}`);
      }
      setAccount(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Sign out failed.");
      throw reason;
    }
  }, [account]);

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
    return <main className="studio-surface grid min-h-dvh w-full place-content-center justify-items-center gap-4 text-sm text-muted-foreground"><BrandMark className="h-20 w-20" /><p role="status">Checking session…</p></main>;
  }

  if (!account) {
    return (
      <main className="studio-surface grid min-h-dvh w-full place-items-center px-4 py-8">
        <form onSubmit={handleSubmit} className="w-full max-w-md space-y-6 rounded-3xl border bg-card p-6 shadow-sm sm:p-9">
          <div className="flex flex-col items-center text-center">
            <BrandMark className="mb-3 h-24 w-24" />
            <span className="mb-2 rounded-full bg-mint-soft px-3 py-1 text-xs font-semibold text-mint-ink">Your own little AI studio</span>
            <h1 className="text-2xl font-bold">Sign in to Mallow</h1>
            <p className="mt-2 text-sm leading-relaxed text-muted-foreground">A friendly space for your ideas, questions, and discoveries.</p>
          </div>
          <label className="block space-y-1.5 text-sm font-medium">
            Username
            <input
              autoComplete="username"
              required
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              className="min-h-12 w-full rounded-xl border border-input bg-background px-4 py-3 text-base font-normal"
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
              className="min-h-12 w-full rounded-xl border border-input bg-background px-4 py-3 text-base font-normal"
            />
          </label>
          {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
          <button
            type="submit"
            disabled={submitting}
            className="min-h-12 w-full rounded-xl bg-primary px-4 py-3 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-ring disabled:opacity-60"
          >
            {submitting ? "Signing in…" : "Sign in"}
          </button>
          <p className="text-center text-xs leading-relaxed text-muted-foreground">Use the account provided by your administrator.<br />Powered by local models. Made for your curiosity.</p>
        </form>
      </main>
    );
  }

  return children;
}
