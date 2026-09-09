import { Check, CircleAlert, Radio } from "lucide-react";
import type { ReactNode } from "react";

export function StatusPill({ children, tone = "neutral", icon }: { children: ReactNode; tone?: "good" | "live" | "warning" | "neutral"; icon?: ReactNode }) {
  const styles = { good: "border-emerald-500/25 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300", live: "border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-300", warning: "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-300", neutral: "border-border bg-muted text-muted-foreground" };
  return <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${styles[tone]}`}>{icon ?? (tone === "good" ? <Check className="size-3" /> : tone === "warning" ? <CircleAlert className="size-3" /> : tone === "live" ? <Radio className="size-3 animate-pulse" /> : null)}{children}</span>;
}
