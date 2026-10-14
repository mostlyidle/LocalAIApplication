import { cn } from "@/lib/utils";

export function BrandMark({ className }: { className?: string }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 120 120" fill="none" className={cn("h-12 w-12 shrink-0", className)}>
      <circle cx="60" cy="60" r="57" fill="var(--color-violet-soft)" />
      <path d="M31 39 25 23l18 8m46 8 6-16-18 8" fill="var(--color-mascot-fur)" stroke="var(--color-ink)" strokeWidth="3" strokeLinejoin="round" />
      <path d="M28 57c0-19 13-33 32-33s32 14 32 33v12c0 19-13 31-32 31S28 88 28 69V57Z" fill="var(--color-mascot-fur)" stroke="var(--color-ink)" strokeWidth="3" />
      <ellipse cx="60" cy="75" rx="24" ry="19" fill="var(--color-mascot-muzzle)" />
      <ellipse cx="47" cy="61" rx="3" ry="4" fill="var(--color-ink)" />
      <ellipse cx="73" cy="61" rx="3" ry="4" fill="var(--color-ink)" />
      <path d="M56 73c0-3 8-3 8 0 0 4-4 5-4 5s-4-1-4-5Z" fill="var(--color-ink)" />
      <path d="M60 79v4m0 0c-3 4-7 4-10 1m10-1c3 4 7 4 10 1" stroke="var(--color-ink)" strokeWidth="2.5" strokeLinecap="round" />
      <path d="m39 75-9-2m9 7-10 1m52-6 9-2m-9 7 10 1" stroke="var(--color-ink)" strokeWidth="1.5" strokeLinecap="round" opacity=".65" />
      <circle cx="37" cy="73" r="3" fill="var(--color-rose-soft)" />
      <circle cx="83" cy="73" r="3" fill="var(--color-rose-soft)" />
    </svg>
  );
}
