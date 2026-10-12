import Image from "next/image";
import { cn } from "@/lib/utils";

export function BrandMark({ className }: { className?: string }) {
  return (
    <Image
      src="/local-ai-logo.svg"
      alt=""
      width={120}
      height={120}
      className={cn("h-12 w-12 shrink-0", className)}
    />
  );
}
