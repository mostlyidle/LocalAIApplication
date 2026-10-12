"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  MessageSquare,
  FileText,
  Database,
  Search,
  Settings,
  Brain,
  Activity,
  BrainCircuit,
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
} from "@/components/ui/sidebar";
import { Badge } from "@/components/ui/badge";

const navItems = [
  { title: "Chat", href: "/chat", icon: MessageSquare },
  { title: "Documents", href: "/documents", icon: FileText },
  { title: "SQL Agent", href: "/sql", icon: Database },
  { title: "RAG Search", href: "/rag", icon: Search },
  { title: "Meetings", href: "/meetings", icon: Activity },
  { title: "Memory", href: "/memory", icon: BrainCircuit },
  { title: "Settings", href: "/settings", icon: Settings },
];

export function AppSidebar() {
  const pathname = usePathname();

  return (
    <Sidebar>
      <SidebarHeader className="border-b px-4 py-3">
        <Link href="/" className="flex items-center gap-2">
          <Brain className="h-6 w-6 text-primary" />
          <div>
            <h1 className="text-sm font-semibold">Local AI</h1>
            <p className="text-xs text-muted-foreground">Fully Local Intelligence</p>
          </div>
        </Link>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Navigation</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {navItems.map((item) => (
                <SidebarMenuItem key={item.href}>
                  <SidebarMenuButton asChild isActive={pathname === item.href || pathname.startsWith(item.href + "/")}>
                    <Link href={item.href}>
                      <item.icon className="h-4 w-4" />
                      <span>{item.title}</span>
                    </Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarFooter className="border-t px-4 py-3">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Activity className="h-3 w-3" />
          <span>Powered by Ollama</span>
          <Badge variant="secondary" className="ml-auto text-[10px]">
            Local
          </Badge>
        </div>
      </SidebarFooter>
    </Sidebar>
  );
}
