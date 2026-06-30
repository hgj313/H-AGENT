import { cn } from "@/lib/utils";
import type { HTMLAttributes, ReactNode } from "react";

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
}

export function Card({ className, children, ...rest }: CardProps) {
  return (
    <div
      {...rest}
      className={cn(
        "rounded-lg border border-brand-100 bg-white p-4 shadow-sm",
        "transition-shadow hover:shadow-md",
        className,
      )}
    >
      {children}
    </div>
  );
}
