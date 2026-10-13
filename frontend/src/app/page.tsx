import Link from "next/link";
import { MessageSquare, FileText, Database, Search, Settings, Activity, BrainCircuit, ArrowUpRight, ArrowRight, Sparkles } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { BrandMark } from "@/components/shared/BrandMark";

const features = [
  {
    title: "Chat",
    description: "A thought partner for questions, big ideas, and little curiosities.",
    href: "/chat",
    icon: MessageSquare,
    color: "bg-violet-soft text-violet-ink",
  },
  {
    title: "Documents",
    description: "Turn your files into summaries, answers, and useful insights.",
    href: "/documents",
    icon: FileText,
    color: "bg-peach-soft text-peach-ink",
  },
  {
    title: "SQL Agent",
    description: "Ask your database a question. Let your agent handle the SQL.",
    href: "/sql",
    icon: Database,
    color: "bg-mint-soft text-mint-ink",
  },
  {
    title: "RAG Search",
    description: "Find the right answer in your knowledge base, with sources.",
    href: "/rag",
    icon: Search,
    color: "bg-sky-soft text-sky-ink",
  },
  {
    title: "Meetings",
    description: "Capture conversations and turn them into notes and next steps.",
    href: "/meetings",
    icon: Activity,
    color: "bg-rose-soft text-rose-ink",
  },
  {
    title: "Memory",
    description: "Give your agents a little context. You decide what they remember.",
    href: "/memory",
    icon: BrainCircuit,
    color: "bg-violet-soft text-violet-ink",
  },
  {
    title: "Settings",
    description: "Make this space yours: models, connections, and appearance.",
    href: "/settings",
    icon: Settings,
    color: "bg-muted text-muted-foreground",
  },
];

export default function HomePage() {
  return (
    <div className="mx-auto max-w-6xl space-y-8 px-4 py-6 sm:px-8 sm:py-10">
      <section className="brand-panel relative flex flex-col-reverse items-start gap-4 overflow-hidden rounded-3xl border p-6 sm:flex-row sm:items-center sm:justify-between sm:p-10">
        <div className="relative max-w-xl">
          <span className="mb-4 inline-flex items-center gap-2 rounded-full border border-primary/15 bg-card/80 px-3 py-1.5 text-xs font-semibold text-primary"><Sparkles className="size-3.5" aria-hidden="true" /> A little help. A lot of possibility.</span>
          <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">Big ideas start<br className="hidden sm:block" /> with a little hello.</h1>
          <p className="mt-4 max-w-md text-base leading-relaxed text-muted-foreground">
            Meet your team of local AI agents. A friendly bunch ready to help you chat, explore, and get things done.
          </p>
          <Button asChild className="mt-6 h-12 rounded-xl px-5">
            <Link href="/chat">Let’s chat <ArrowRight className="size-4" aria-hidden="true" /></Link>
          </Button>
        </div>
        <div aria-hidden="true" className="relative self-center sm:px-6">
          <div className="absolute inset-0 rounded-full bg-peach-soft" />
          <BrandMark className="relative h-28 w-28 sm:h-48 sm:w-48" />
          <span className="absolute -bottom-1 right-0 rotate-6 rounded-xl border bg-card px-3 py-2 text-sm font-semibold text-primary shadow-xs">Hi, curious human!</span>
        </div>
      </section>
      <section aria-labelledby="agents-heading">
        <div className="mb-5 flex flex-wrap items-end justify-between gap-2">
          <div>
            <h2 id="agents-heading" className="text-xl font-bold">Your helpful little team</h2>
            <p className="mt-1 text-sm text-muted-foreground">Pick a space and see what we can do together.</p>
          </div>
          <span className="rounded-full bg-mint-soft px-3 py-1 text-xs font-medium text-mint-ink">Powered by Ollama</span>
        </div>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {features.map((feature) => (
          <Link key={feature.href} href={feature.href} className="group rounded-2xl">
            <Card className="h-full gap-3 transition-colors hover:border-primary/40 hover:bg-card/80">
              <CardHeader className="pb-3">
                <div className="mb-2 flex items-center justify-between">
                  <span className={`grid size-12 place-items-center rounded-2xl ${feature.color}`}><feature.icon className="size-6" aria-hidden="true" /></span>
                  <ArrowUpRight className="size-4 text-muted-foreground transition-colors group-hover:text-primary" aria-hidden="true" />
                </div>
                <CardTitle className="text-lg">{feature.title}</CardTitle>
              </CardHeader>
              <CardContent>
                <CardDescription className="leading-relaxed">{feature.description}</CardDescription>
              </CardContent>
            </Card>
          </Link>
        ))}
        </div>
      </section>
    </div>
  );
}
