import { cn } from "@/lib/utils";

export interface SkeletonProps {
  className?: string;
  /** 预设：text / circle / rect */
  variant?: "text" | "circle" | "rect";
}

const VARIANT_CLASS = {
  text: "h-3 w-full rounded",
  circle: "h-10 w-10 rounded-full",
  rect: "h-24 w-full rounded-md",
};

export function Skeleton({ className, variant = "text" }: SkeletonProps) {
  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "animate-pulse bg-brand-100",
        VARIANT_CLASS[variant],
        className,
      )}
    />
  );
}
