import { Check, Mic, MonitorUp, ShieldCheck, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { CapabilityCheck } from "@/types/meeting";
import { StatusPill } from "./StatusPill";

const icons = { microphone: Mic, system: MonitorUp, permissions: ShieldCheck };

interface PreflightPanelProps {
  checks: CapabilityCheck[];
  onContinue: () => void;
  loading?: boolean;
  onRequestPermissions?: () => Promise<void>;
  onOpenSettings?: () => Promise<void>;
  onRecheck?: () => Promise<void>;
}

export function PreflightPanel({
  checks,
  onContinue,
  loading = false,
  onRequestPermissions,
  onOpenSettings,
  onRecheck,
}: PreflightPanelProps) {
  const ready = checks.length > 0 && checks.every((check) => !check.required || check.passed);
  const browserUnavailable = checks.some((check) => check.id === "desktop");
  return (
    <section className="rounded-2xl border bg-card p-5 shadow-sm sm:p-7" aria-labelledby="preflight-title">
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
            Step 1 of 2
          </p>
          <h2 id="preflight-title" className="text-xl font-semibold tracking-tight">
            Check capture readiness
          </h2>
          <p className="mt-2 max-w-lg text-sm leading-6 text-muted-foreground">
            {browserUnavailable ? (
              <>
                Meetings need the native desktop app. Start it from the repository root with{" "}
                <code className="rounded bg-muted px-1">make dev-desktop</code>, then open Meetings in its window.
              </>
            ) : (
              "Check microphone, system audio, and backend readiness before starting."
            )}
          </p>
        </div>
        <StatusPill tone={ready ? "good" : "warning"}>
          {ready ? "Ready to continue" : "Action needed"}
        </StatusPill>
      </div>
      <div className="divide-y rounded-xl border">
        {checks.length === 0 ? (
          <div className="p-5 text-sm text-muted-foreground">Checking native capture capabilities…</div>
        ) : (
          checks.map((check) => {
            const Icon = icons[check.id as keyof typeof icons] ?? ShieldCheck;
            return (
              <div key={check.id} className="flex items-center gap-4 p-4">
                <div className={`rounded-lg p-2.5 ${check.passed ? "bg-mint-soft text-mint-ink" : "bg-peach-soft text-peach-ink"}`}>
                  <Icon className="size-4" />
                </div>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">{check.label}</p>
                  <p className="mt-0.5 text-xs text-muted-foreground">{check.detail}</p>
                </div>
                {check.state === "not_applicable" ? (
                  <span className="text-xs text-muted-foreground">Not applicable</span>
                ) : check.passed ? (
                  <Check className="size-5 text-mint-ink" />
                ) : (
                  <X className="size-5 text-peach-ink" />
                )}
              </div>
            );
          })
        )}
      </div>
      {!ready && checks.length > 0 && (
        <p className="mt-4 rounded-lg bg-peach-soft px-3 py-2 text-xs leading-5 text-peach-ink">
          {browserUnavailable
            ? "Browser mode cannot request meeting capture permissions. Open the native desktop window to continue."
            : "Required capture permissions and native services must be ready before starting."}
        </p>
      )}
      <div className="mt-6 flex flex-wrap justify-between gap-3">
        <div className="flex flex-wrap gap-2">
          {!browserUnavailable && onRequestPermissions && (
            <Button type="button" variant="outline" size="sm" disabled={loading} onClick={() => void onRequestPermissions()}>
              Request permissions
            </Button>
          )}
          {!browserUnavailable && onOpenSettings && (
            <Button type="button" variant="ghost" size="sm" disabled={loading} onClick={() => void onOpenSettings()}>
              Open system settings
            </Button>
          )}
          {!browserUnavailable && onRecheck && (
            <Button type="button" variant="ghost" size="sm" disabled={loading} onClick={() => void onRecheck()}>
              Recheck
            </Button>
          )}
        </div>
        <Button type="button" size="lg" disabled={!ready || loading} onClick={onContinue}>
          Continue to consent
        </Button>
      </div>
    </section>
  );
}
