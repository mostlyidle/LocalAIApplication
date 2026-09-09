import { Eye, LockKeyhole, Mic2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { AudioSourceState } from "@/types/meeting";

export function ConsentPanel({ sources, given, onChange, onStart, onBack }: { sources: AudioSourceState[]; given: boolean; onChange: (value: boolean) => void; onStart: () => void; onBack: () => void }) {
  return <section className="rounded-2xl border bg-card p-5 shadow-sm sm:p-7" aria-labelledby="consent-title">
    <p className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">Step 2 of 2</p><h2 id="consent-title" className="text-xl font-semibold tracking-tight">Confirm before recording</h2><p className="mt-2 max-w-xl text-sm leading-6 text-muted-foreground">When native capture is connected, everyone in the meeting should know that audio and a transcript will be captured.</p>
    <div className="mt-6 grid gap-3 sm:grid-cols-2">{sources.map((source) => <div key={source.source} className="flex items-center gap-3 rounded-xl border bg-muted/30 p-4"><Mic2 className="size-4 text-muted-foreground" /><div><p className="text-sm font-medium">{source.label} audio</p><p className="text-xs text-muted-foreground">{source.detail}</p></div></div>)}</div>
    <div className="mt-6 space-y-3 rounded-xl border border-primary/20 bg-primary/[0.04] p-4"><div className="flex gap-3"><Eye className="mt-0.5 size-4 shrink-0 text-primary" /><p className="text-sm leading-6">I confirm that participants have been told this meeting will be recorded and transcribed.</p></div><label className="flex cursor-pointer items-start gap-3 border-t pt-3 text-sm"><input type="checkbox" checked={given} onChange={(event) => onChange(event.target.checked)} className="mt-0.5 size-4 accent-primary" /> <span>I understand and want to start recording.</span></label></div>
    <div className="mt-6 flex items-center justify-between gap-3"><Button variant="ghost" onClick={onBack}>Back</Button><Button size="lg" disabled={!given} onClick={onStart}><LockKeyhole className="size-4" />Start visible recording</Button></div>
  </section>;
}
