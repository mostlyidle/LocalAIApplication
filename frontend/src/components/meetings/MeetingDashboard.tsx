"use client";

import { CalendarClock, Sparkles } from "lucide-react";
import { PreflightPanel } from "./PreflightPanel";
import { ConsentPanel } from "./ConsentPanel";
import { LiveMeeting } from "./LiveMeeting";
import { ReviewPanel } from "./ReviewPanel";
import { useMeetingController } from "@/app/meetings/useMeetingController";

export function MeetingDashboard() {
  const controller = useMeetingController();
  return <div className="studio-surface min-h-full"><div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-10 lg:py-12"><header className="mb-9 flex flex-col justify-between gap-5 sm:flex-row sm:items-end"><div><div className="mb-4 flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.2em] text-violet-ink"><Sparkles className="size-4" />Local meetings</div><h1 className="text-3xl font-semibold tracking-[-0.03em] sm:text-4xl">Make space for the conversation.</h1><p className="mt-3 max-w-xl text-sm leading-6 text-muted-foreground">A meeting workspace connected to native capture and local processing.</p></div><div className="flex items-center gap-2 text-xs text-muted-foreground"><CalendarClock className="size-4" />Meeting workspace</div></header>{controller.error && <div role="alert" className="mb-6 rounded-xl border border-rose-ink/20 bg-rose-soft px-4 py-3 text-sm text-rose-ink">{controller.error}</div>}{controller.phase === "preflight" && <PreflightPanel checks={controller.capabilities} loading={controller.isLoading} onContinue={controller.beginConsent} onRequestPermissions={controller.requestPermissions} onOpenSettings={controller.openPermissionSettings} onRecheck={controller.recheck} />}{controller.phase === "consent" && <ConsentPanel sources={controller.sources} given={controller.consentGiven} onChange={controller.setConsent} onStart={controller.start} onBack={controller.reset} />}{controller.phase === "live" && <LiveMeeting meeting={controller.meeting} sources={controller.sources} onStop={controller.stop} />}{controller.phase === "review" && <ReviewPanel meeting={controller.meeting} onReset={controller.reset} />}</div></div>;
}
