import { Check, CircleAlert, Radio } from "lucide-react";
import type { ReactNode } from "react";

export function StatusPill({ children, tone = "neutral", icon }: { children: ReactNode; tone?: "good" | "live" | "warning" | "neutral"; icon?: ReactNode }) {
  const styles = { good: "border-mint-ink/20 bg-mint-soft text-mint-ink", live: "border-rose-ink/20 bg-rose-soft text-rose-ink", warning: "border-peach-ink/20 bg-peach-soft text-peach-ink", neutral: "border-border bg-muted text-muted-foreground" };
  return <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${styles[tone]}`}>{icon ?? (tone === "good" ? <Check className="size-3" /> : tone === "warning" ? <CircleAlert className="size-3" /> : tone === "live" ? <Radio className="size-3 animate-pulse" /> : null)}{children}</span>;
}
