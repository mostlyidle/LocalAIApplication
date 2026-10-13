"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  MessageSquare,
  FileText,
  Database,
  Search,
  Settings,
  Activity,
  BrainCircuit,
  ListTodo,
  Github,
} from "lucide-react";
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarFooter,
  SidebarTrigger,
  useSidebar,
} from "@/components/ui/sidebar";
import { Badge } from "@/components/ui/badge";
import { BrandMark } from "./BrandMark";

const navItems = [
  { title: "Chat", href: "/chat", icon: MessageSquare, tone: "bg-violet-soft text-violet-ink" },
  { title: "Documents", href: "/documents", icon: FileText, tone: "bg-peach-soft text-peach-ink" },
  { title: "SQL Agent", href: "/sql", icon: Database, tone: "bg-mint-soft text-mint-ink" },
  { title: "RAG Search", href: "/rag", icon: Search, tone: "bg-sky-soft text-sky-ink" },
  { title: "Meetings", href: "/meetings", icon: Activity, tone: "bg-rose-soft text-rose-ink" },
  { title: "Memory", href: "/memory", icon: BrainCircuit, tone: "bg-violet-soft text-violet-ink" },
  { title: "Action Planner", href: "/action-items", icon: ListTodo, tone: "bg-peach-soft text-peach-ink" },
  { title: "GitHub Agent", href: "/github", icon: Github, tone: "bg-sky-soft text-sky-ink" },
  { title: "Settings", href: "/settings", icon: Settings, tone: "bg-muted text-muted-foreground" },
];

export function AppSidebar() {
  const pathname = usePathname();
  const { isMobile, setOpenMobile } = useSidebar();

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="px-5 pb-5 pt-6">
        <Link href="/" className="flex items-center gap-2.5 rounded-lg">
          <BrandMark />
          <div>
            <span className="text-xl font-bold tracking-tight">Local AI</span>
            <p className="text-xs text-muted-foreground">Your little AI studio</p>
          </div>
        </Link>
        <SidebarTrigger className="absolute right-3 top-3 size-11 md:hidden" />
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup className="px-3">
          <SidebarGroupLabel className="px-3 text-[11px] font-semibold uppercase tracking-widest">Navigation</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu className="gap-1.5">
              {navItems.map((item) => (
                <SidebarMenuItem key={item.href}>
                  <SidebarMenuButton
                    asChild
                    tooltip={item.title}
                    className="relative h-11 rounded-xl px-3 font-medium transition-colors hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground data-[active=true]:bg-sidebar-accent data-[active=true]:font-semibold data-[active=true]:text-sidebar-accent-foreground data-[active=true]:shadow-xs data-[active=true]:before:absolute data-[active=true]:before:left-1 data-[active=true]:before:top-2.5 data-[active=true]:before:bottom-2.5 data-[active=true]:before:w-1 data-[active=true]:before:rounded-full data-[active=true]:before:bg-primary"
                    isActive={pathname === item.href || pathname.startsWith(item.href + "/")}
                  >
                    <Link href={item.href} onClick={() => { if (isMobile) setOpenMobile(false); }} aria-current={pathname === item.href || pathname.startsWith(item.href + "/") ? "page" : undefined}>
                      <span className={`grid size-8 shrink-0 place-items-center rounded-lg transition-colors ${pathname === item.href || pathname.startsWith(item.href + "/") ? item.tone : "bg-muted/60 text-muted-foreground group-hover:bg-accent group-hover:text-foreground"}`}>
                        <item.icon className="h-4 w-4" aria-hidden="true" />
                      </span>
                      <span>{item.title}</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter className="gap-4 px-5 pb-5 pt-3">
        <div className="rounded-2xl border border-mint-ink/15 bg-mint-soft p-4 text-mint-ink">
          <p className="text-sm font-semibold">Big ideas. Close to home.</p>
          <p className="mt-1 text-xs leading-relaxed">Fully Local Intelligence</p>
        </div>
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Activity className="h-3 w-3" aria-hidden="true" />
          <span>Powered by Ollama</span>
          <Badge variant="secondary" className="ml-auto text-[10px]">
            Local
          </Badge>
        </div>
      </SidebarFooter>
    </Sidebar>
  );
}
