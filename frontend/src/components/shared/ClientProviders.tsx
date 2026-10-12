"use client";

import type { ReactNode } from "react";
import { SidebarProvider } from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Toaster } from "@/components/ui/sonner";
import { ThemeProvider } from "./ThemeProvider";
import { AuthProvider, AuthenticatedShell } from "./AuthProvider";
import { AppSidebar } from "./AppSidebar";
import { Header } from "./Header";

export function ClientProviders({ children }: { children: ReactNode }) {
  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
      <TooltipProvider>
        <AuthProvider>
          <SidebarProvider>
            <AuthenticatedShell>
              <AppSidebar />
              <a href="#main-content" className="sr-only z-50 rounded-lg bg-primary p-3 text-primary-foreground focus:not-sr-only focus:fixed focus:left-4 focus:top-4">Skip to content</a>
              <div className="studio-surface flex h-dvh min-w-0 flex-1 flex-col overflow-hidden">
                <Header />
                <main id="main-content" tabIndex={-1} className="min-h-0 flex-1 overflow-auto">{children}</main>
              </div>
            </AuthenticatedShell>
          </SidebarProvider>
          <Toaster />
        </AuthProvider>
      </TooltipProvider>
    </ThemeProvider>
  );
}
