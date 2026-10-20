/* Hallmark · genre: playful · macrostructure: Workbench · design-system: design.md · designed-as-app */

import Link from "next/link";
import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  BrainCircuit,
  BriefcaseBusiness,
  Database,
  FileText,
  Github,
  ListTodo,
  MessageSquare,
  Search,
  Settings,
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { BrandMark } from "@/components/shared/BrandMark";

const workspaces = [
  {
    title: "Ask & explore",
    description: "Start with a question, a file, or a source you want to search.",
    items: [
      { title: "Chat", description: "Think something through", href: "/chat", icon: MessageSquare },
      { title: "Documents", description: "Ask questions about your files", href: "/documents", icon: FileText },
      { title: "RAG Search", description: "Find grounded answers with sources", href: "/rag", icon: Search },
    ],
  },
  {
    title: "Get things done",
    description: "Work with data, conversations, and project details.",
    items: [
      { title: "SQL Agent", description: "Explore a connected database", href: "/sql", icon: Database },
      { title: "Meetings", description: "Capture notes and next steps", href: "/meetings", icon: Activity },
      { title: "Action Planner", description: "Keep track of what comes next", href: "/action-items", icon: ListTodo },
      { title: "GitHub Agent", description: "Explore repository work", href: "/github", icon: Github },
      { title: "Resume Rater", description: "Compare candidates against a job rubric", href: "/resume-rater", icon: BriefcaseBusiness },
    ],
  },
  {
    title: "Make it yours",
    description: "Shape the context and setup behind your workspace.",
    items: [
      { title: "Memory", description: "Choose what your agents remember", href: "/memory", icon: BrainCircuit },
      { title: "Settings", description: "Models, connections, and appearance", href: "/settings", icon: Settings },
    ],
  },
];

export default function HomePage() {
  return (
    <div className="mx-auto max-w-6xl space-y-10 px-4 py-6 sm:px-8 sm:py-10">
      <section className="relative flex flex-col-reverse items-start gap-5 overflow-hidden rounded-3xl border bg-violet-soft/55 p-6 sm:flex-row sm:items-center sm:justify-between sm:p-10">
        <div className="relative max-w-xl">
          <span className="mb-4 inline-flex items-center gap-2 rounded-full border border-primary/15 bg-card px-3 py-1.5 text-xs font-semibold text-violet-ink">
            <Sparkles className="size-3.5" aria-hidden="true" /> A little help, close to home
          </span>
          <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">A cozy place for big ideas.</h1>
          <p className="mt-4 max-w-md text-base leading-relaxed text-muted-foreground">
            Mallow brings your local models, documents, and everyday AI tools into one friendly workspace.
          </p>
          <Button asChild className="mt-6 h-12 px-5">
            <Link href="/chat">Start a chat <ArrowRight className="size-4" aria-hidden="true" /></Link>
          </Button>
        </div>
        <div aria-hidden="true" className="relative flex flex-col items-center gap-2 self-center sm:block sm:px-8">
          <BrandMark className="relative h-28 w-28 sm:h-40 sm:w-40" />
          <span className="rotate-3 rounded-xl border bg-card px-3 py-2 text-sm font-semibold text-violet-ink shadow-sm sm:absolute sm:-bottom-1 sm:right-0">Hello, curious human!</span>
        </div>
      </section>

      <section aria-labelledby="workspaces-heading">
        <div className="mb-5 flex flex-wrap items-end justify-between gap-2">
          <div>
            <h2 id="workspaces-heading" className="text-xl font-semibold">Your workspaces</h2>
            <p className="mt-1 text-sm text-muted-foreground">Choose a place to pick up an idea or get something done.</p>
          </div>
          <span className="rounded-full bg-mint-soft px-3 py-1 text-xs font-medium text-mint-ink">Runs locally with Ollama</span>
        </div>
        <div className="grid gap-4 lg:grid-cols-3">
          {workspaces.map((workspace) => (
            <section key={workspace.title} className="rounded-2xl border bg-card p-4 sm:p-5" aria-label={workspace.title}>
              <h3 className="text-base font-semibold">{workspace.title}</h3>
              <p className="mt-1 min-h-10 text-sm leading-5 text-muted-foreground">{workspace.description}</p>
              <div className="mt-3 divide-y">
                {workspace.items.map((item) => (
                  <Link key={item.href} href={item.href} className="group flex min-h-16 items-center gap-3 rounded-xl px-2 py-2 transition-colors hover:bg-muted/70 focus-visible:outline-2 focus-visible:outline-ring">
                    <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-violet-soft text-violet-ink"><item.icon className="size-4" aria-hidden="true" /></span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-semibold">{item.title}</span>
                      <span className="mt-0.5 block text-xs leading-4 text-muted-foreground">{item.description}</span>
                    </span>
                    <ArrowUpRight className="size-4 shrink-0 text-muted-foreground transition-colors group-hover:text-violet-ink" aria-hidden="true" />
                  </Link>
                ))}
              </div>
            </section>
          ))}
        </div>
      </section>
    </div>
  );
}
