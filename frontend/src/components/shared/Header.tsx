"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { Moon, Sun, Monitor, LogOut } from "lucide-react";
import { toast } from "sonner";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Separator } from "@/components/ui/separator";
import { useTheme } from "next-themes";
import { useAuth } from "./AuthProvider";
import * as api from "@/lib/api";
import { cn } from "@/lib/utils";

const pageTitles: Record<string, string> = {
  "/": "Dashboard",
  "/chat": "Chat",
  "/documents": "Documents",
  "/sql": "SQL Agent",
  "/rag": "RAG Search",
  "/meetings": "Meetings",
  "/memory": "Memory",
  "/action-items": "Action Planner",
  "/github": "GitHub Project Agent",
  "/resume-rater": "Resume Rater",
  "/settings": "Settings",
};

function SystemStatusPill() {
  const [health, setHealth] = useState<"connected" | "disconnected" | "checking">("checking");

  useEffect(() => {
    let active = true;
    const checkHealth = () => {
      api.getHealth()
        .then((data) => {
          if (active) setHealth(data.ollama.status === "healthy" ? "connected" : "disconnected");
        })
        .catch(() => {
          if (active) setHealth("disconnected");
        });
    };
    checkHealth();
    const interval = window.setInterval(checkHealth, 30_000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, []);

  const label = health === "connected" ? "Ollama Online"
    : health === "disconnected" ? "Ollama Offline" : "Checking Ollama";

  return (
    <div aria-live="polite" className="hidden items-center gap-2 rounded-full border bg-background/80 px-2.5 py-1 text-xs lg:flex">
      <span aria-hidden="true" className={cn(
        "size-2 rounded-full",
        health === "connected" && "bg-mint-ink",
        health === "disconnected" && "bg-destructive",
        health === "checking" && "bg-peach-ink",
      )} />
      <span className="font-medium text-muted-foreground">{label}</span>
    </div>
  );
}

export function Header() {
  const pathname = usePathname();
  const { theme, setTheme } = useTheme();
  const { account, signOut } = useAuth();

  const title = pageTitles[pathname] ?? "Mallow";

  return (
    <header className="flex h-16 shrink-0 items-center gap-3 border-b bg-card/80 px-4 sm:px-6">
      <SidebarTrigger className="size-11" />
      <Separator orientation="vertical" className="data-[orientation=vertical]:h-5" />
      <span className="min-w-0 flex-1 truncate text-sm font-semibold" title={title}>{title}</span>
      <div className="ml-auto flex shrink-0 items-center gap-2">
        <SystemStatusPill />
        {account && (
          <>
            <span className="hidden max-w-40 items-center gap-2 text-sm font-medium xl:flex">
              <span aria-hidden="true" className="grid size-8 shrink-0 place-items-center rounded-full bg-peach-soft text-peach-ink">{account.display_name.slice(0, 1).toUpperCase()}</span>
              <span className="truncate" title={account.display_name}>{account.display_name}</span>
            </span>
            <Button
              variant="ghost"
              size="sm"
              className="min-h-11"
              onClick={() => void signOut().catch((error: unknown) => toast.error(error instanceof Error ? error.message : "Sign out failed."))}
            >
              <LogOut className="h-4 w-4" aria-hidden="true" />
              Sign out
            </Button>
          </>
        )}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="icon" className="h-11 w-11 rounded-full" aria-label="Change color theme">
              {theme === "dark" ? (
                <Moon className="h-4 w-4" />
              ) : theme === "light" ? (
                <Sun className="h-4 w-4" />
              ) : (
                <Monitor className="h-4 w-4" />
              )}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={() => setTheme("light")}>
              <Sun className="mr-2 h-4 w-4" />
              Light
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => setTheme("dark")}>
              <Moon className="mr-2 h-4 w-4" />
              Dark
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => setTheme("system")}>
              <Monitor className="mr-2 h-4 w-4" />
              System
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
