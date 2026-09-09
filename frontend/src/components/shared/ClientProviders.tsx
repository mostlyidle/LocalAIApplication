"use client";

import type { ReactNode } from "react";
import { SidebarProvider } from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Toaster } from "@/components/ui/sonner";
import { ThemeProvider } from "./ThemeProvider";
import { AppSidebar } from "./AppSidebar";
import { Header } from "./Header";

export function ClientProviders({ children }: { children: ReactNode }) {
  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem>
      <TooltipProvider>
        <SidebarProvider>
          <AppSidebar />
          <div className="flex flex-1 flex-col overflow-hidden">
            <Header />
            <main className="flex-1 overflow-auto">{children}</main>
          </div>
        </SidebarProvider>
        <Toaster />
      </TooltipProvider>
    </ThemeProvider>
  );
}
