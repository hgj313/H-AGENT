"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { ROUTES } from "@/constants/routes";

const LINKS: Array<{ href: string; label: string }> = [
  { href: ROUTES.agentHub, label: "Agent 中心" },
  { href: ROUTES.chat, label: "通用对话" },
  { href: ROUTES.designReview, label: "设计审查" },
];

export function TopNav() {
  const pathname = usePathname();
  return (
    <header className="sticky top-0 z-10 border-b border-brand-100 bg-white/80 backdrop-blur">
      <div className="mx-auto flex max-w-7xl items-center gap-6 px-6 py-3">
        <Link
          href={ROUTES.agentHub}
          className="text-lg font-semibold text-brand-500"
        >
          H-Agent
        </Link>
        <nav className="flex items-center gap-1" aria-label="主导航">
          {LINKS.map((l) => {
            const active =
              l.href === ROUTES.agentHub
                ? pathname === ROUTES.agentHub
                : pathname?.startsWith(l.href);
            return (
              <Link
                key={l.href}
                href={l.href}
                className={cn(
                  "rounded-md px-3 py-1.5 text-sm transition-colors",
                  active
                    ? "bg-brand-50 text-brand-500"
                    : "text-gray-600 hover:bg-brand-50 hover:text-brand-500",
                )}
                aria-current={active ? "page" : undefined}
              >
                {l.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
