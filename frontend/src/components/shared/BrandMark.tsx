import { cn } from "@/lib/utils";

export function BrandMark({ className }: { className?: string }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 120 120" fill="none" className={cn("h-12 w-12 shrink-0", className)}>
      <circle cx="60" cy="60" r="57" fill="var(--color-mascot-badge)" />
      <circle cx="37" cy="49" r="10" fill="var(--color-mascot-fur)" stroke="var(--color-mascot-outline)" strokeWidth="3" />
      <circle cx="83" cy="49" r="10" fill="var(--color-mascot-fur)" stroke="var(--color-mascot-outline)" strokeWidth="3" />
      <circle cx="37" cy="49" r="4.5" fill="var(--color-mascot-muzzle)" />
      <circle cx="83" cy="49" r="4.5" fill="var(--color-mascot-muzzle)" />
      <path d="M28 60c0-19 13-32 32-32s32 13 32 32v12c0 18-13 29-32 29S28 90 28 72V60Z" fill="var(--color-mascot-fur)" stroke="var(--color-mascot-outline)" strokeWidth="3" />
      <ellipse cx="60" cy="75" rx="27" ry="19" fill="var(--color-mascot-muzzle)" />
      <ellipse cx="47" cy="59" rx="3.5" ry="4.5" fill="var(--color-mascot-outline)" />
      <ellipse cx="73" cy="59" rx="3.5" ry="4.5" fill="var(--color-mascot-outline)" />
      <circle cx="48" cy="57" r="1.25" fill="var(--color-mascot-muzzle)" />
      <circle cx="74" cy="57" r="1.25" fill="var(--color-mascot-muzzle)" />
      <path d="M55 70c0-3.5 10-3.5 10 0 0 4-5 6-5 6s-5-2-5-6Z" fill="var(--color-mascot-outline)" />
      <path d="M60 76v5m0 0c-3.5 4-7.5 4-11 1m11-1c3.5 4 7.5 4 11 1" stroke="var(--color-mascot-outline)" strokeWidth="2.5" strokeLinecap="round" />
      <path d="m37 73-8-2m8 7-9 1m55-6 8-2m-8 7 9 1" stroke="var(--color-mascot-outline)" strokeWidth="1.5" strokeLinecap="round" opacity=".55" />
      <circle cx="38" cy="71" r="3.5" fill="var(--color-mascot-cheek)" />
      <circle cx="82" cy="71" r="3.5" fill="var(--color-mascot-cheek)" />
    </svg>
  );
}
