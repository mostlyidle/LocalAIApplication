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

const navGroups = [
  { title: "Ask & explore", items: [
    { title: "Chat", href: "/chat", icon: MessageSquare },
    { title: "Documents", href: "/documents", icon: FileText },
    { title: "RAG Search", href: "/rag", icon: Search },
  ] },
  { title: "Get things done", items: [
    { title: "SQL Agent", href: "/sql", icon: Database },
    { title: "Meetings", href: "/meetings", icon: Activity },
    { title: "Action Planner", href: "/action-items", icon: ListTodo },
    { title: "GitHub Agent", href: "/github", icon: Github },
    { title: "Memory", href: "/memory", icon: BrainCircuit },
  ] },
  { title: "Personalize", items: [{ title: "Settings", href: "/settings", icon: Settings }] },
];

export function AppSidebar() {
  const pathname = usePathname();
  const { isMobile, setOpenMobile } = useSidebar();

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader className="px-5 pb-5 pt-6 group-data-[collapsible=icon]:items-center group-data-[collapsible=icon]:px-2 group-data-[collapsible=icon]:py-3">
        <Link href="/" className="flex items-center gap-2.5 rounded-lg group-data-[collapsible=icon]:justify-center">
          <BrandMark />
          <div className="group-data-[collapsible=icon]:hidden">
            <span className="text-xl font-bold tracking-tight">Mallow</span>
            <p className="text-xs text-muted-foreground">Local AI studio</p>
          </div>
        </Link>
        <SidebarTrigger className="absolute right-3 top-3 size-11 md:hidden" />
      </SidebarHeader>
      <SidebarContent>
        {navGroups.map((group) => (
          <SidebarGroup key={group.title} className="px-3">
            <SidebarGroupLabel className="px-3 text-[11px] font-semibold uppercase tracking-widest">{group.title}</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu className="gap-1">
              {group.items.map((item) => {
                const active = pathname === item.href || pathname.startsWith(item.href + "/");
                return (
                <SidebarMenuItem key={item.href}>
                  <SidebarMenuButton
                    asChild
                    tooltip={item.title}
                    className="relative h-10 rounded-xl px-2.5 font-medium transition-colors hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground data-[active=true]:bg-sidebar-accent data-[active=true]:font-semibold data-[active=true]:text-sidebar-accent-foreground data-[active=true]:before:absolute data-[active=true]:before:left-1 data-[active=true]:before:top-2.5 data-[active=true]:before:bottom-2.5 data-[active=true]:before:w-0.5 data-[active=true]:before:rounded-full data-[active=true]:before:bg-primary"
                    isActive={active}
                  >
                    <Link href={item.href} onClick={() => { if (isMobile) setOpenMobile(false); }} aria-current={active ? "page" : undefined}>
                      <span className={`grid size-8 shrink-0 place-items-center rounded-lg transition-colors group-data-[collapsible=icon]:size-4! ${active ? "bg-primary/10 text-primary" : "text-muted-foreground group-hover:text-foreground"}`}>
                        <item.icon className="h-4 w-4" aria-hidden="true" />
                      </span>
                      <span>{item.title}</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
                );
              })}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ))}
      </SidebarContent>
      <SidebarFooter className="gap-4 px-5 pb-5 pt-3 group-data-[collapsible=icon]:hidden">
        <div className="rounded-2xl border border-mint-ink/15 bg-mint-soft p-4 text-mint-ink">
          <p className="text-sm font-semibold">Big ideas. Close to home.</p>
          <p className="mt-1 text-xs leading-relaxed">Your AI stays close to home.</p>
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
