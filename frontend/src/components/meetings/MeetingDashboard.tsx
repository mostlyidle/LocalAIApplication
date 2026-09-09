"use client";

import { CalendarClock, Info, Sparkles } from "lucide-react";
import { PreflightPanel } from "./PreflightPanel";
import { ConsentPanel } from "./ConsentPanel";
import { LiveMeeting } from "./LiveMeeting";
import { ReviewPanel } from "./ReviewPanel";
import { useMeetingController } from "@/app/meetings/useMeetingController";

export function MeetingDashboard() {
  const controller = useMeetingController();
  return <div className="min-h-full bg-[radial-gradient(circle_at_top_right,oklch(0.96_0.04_250),transparent_35%),radial-gradient(circle_at_10%_20%,oklch(0.98_0.03_145),transparent_30%)]"><div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-10 lg:py-12"><header className="mb-9 flex flex-col justify-between gap-5 sm:flex-row sm:items-end"><div><div className="mb-4 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.2em] text-primary"><Sparkles className="size-4" />Local meetings</div><h1 className="text-3xl font-semibold tracking-[-0.03em] sm:text-4xl">Make space for the conversation.</h1><p className="mt-3 max-w-xl text-sm leading-6 text-muted-foreground">A meeting workspace connected to native capture and local processing.</p></div><div className="flex items-center gap-2 text-xs text-muted-foreground"><CalendarClock className="size-4" />Phase 2 live meeting</div></header><div className="mb-6 flex items-start gap-3 rounded-xl border border-blue-500/20 bg-blue-500/[0.05] px-4 py-3 text-xs leading-5 text-muted-foreground"><Info className="mt-0.5 size-4 shrink-0 text-blue-600" />Native desktop capture and backend wiring are required. This page is unavailable in a browser.</div>{controller.error && <div role="alert" className="mb-6 rounded-xl border border-rose-500/20 bg-rose-500/[0.05] px-4 py-3 text-sm text-rose-700 dark:text-rose-300">{controller.error}</div>}{controller.phase === "preflight" && <PreflightPanel checks={controller.capabilities} loading={controller.isLoading} onContinue={controller.beginConsent} onRequestPermissions={controller.requestPermissions} onOpenSettings={controller.openPermissionSettings} onRecheck={controller.recheck} />}{controller.phase === "consent" && <ConsentPanel sources={controller.sources} given={controller.consentGiven} onChange={controller.setConsent} onStart={controller.start} onBack={controller.reset} />}{controller.phase === "live" && <LiveMeeting meeting={controller.meeting} sources={controller.sources} onStop={controller.stop} />}{controller.phase === "review" && <ReviewPanel meeting={controller.meeting} onReset={controller.reset} />}</div></div>;
}
