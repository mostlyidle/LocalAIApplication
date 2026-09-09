import Link from "next/link";
import { MessageSquare, FileText, Database, Search, Settings, Brain } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const features = [
  {
    title: "Chat",
    description: "Multi-modal conversational AI with streaming responses",
    href: "/chat",
    icon: MessageSquare,
    color: "text-blue-500",
  },
  {
    title: "Documents",
    description: "Upload, parse, and analyze documents with AI",
    href: "/documents",
    icon: FileText,
    color: "text-amber-500",
  },
  {
    title: "SQL Agent",
    description: "Natural language to SQL query generation and execution",
    href: "/sql",
    icon: Database,
    color: "text-emerald-500",
  },
  {
    title: "RAG Search",
    description: "Semantic search across your ingested knowledge base",
    href: "/rag",
    icon: Search,
    color: "text-violet-500",
  },
  {
    title: "Settings",
    description: "Configure models, databases, and MCP servers",
    href: "/settings",
    icon: Settings,
    color: "text-muted-foreground",
  },
];

export default function HomePage() {
  return (
    <div className="container mx-auto max-w-5xl p-6">
      <div className="mb-8 flex items-center gap-3">
        <Brain className="h-8 w-8 text-primary" />
        <div>
          <h1 className="text-2xl font-bold">Local AI Application</h1>
          <p className="text-muted-foreground">
            Fully local, production-grade AI — zero cloud dependencies
          </p>
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {features.map((feature) => (
          <Link key={feature.href} href={feature.href}>
            <Card className="h-full transition-colors hover:bg-accent">
              <CardHeader className="pb-3">
                <feature.icon className={`h-6 w-6 ${feature.color}`} />
                <CardTitle className="text-base">{feature.title}</CardTitle>
              </CardHeader>
              <CardContent>
                <CardDescription>{feature.description}</CardDescription>
              </CardContent>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
