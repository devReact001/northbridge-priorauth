"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/", label: "Review queue", match: (p: string) => p === "/" || p.startsWith("/cases/") && p !== "/cases/new" },
  { href: "/cases/new", label: "New case", match: (p: string) => p === "/cases/new" },
  { href: "/dashboard", label: "Dashboard", match: (p: string) => p.startsWith("/dashboard") },
];

export function Nav() {
  const path = usePathname() ?? "/";
  return (
    <header className="border-b border-line bg-surface">
      <div className="mx-auto flex w-full max-w-7xl flex-wrap items-center gap-x-8 gap-y-2 px-4 py-3 sm:px-6">
        <Link href="/" className="flex items-baseline gap-2">
          <span className="text-base font-semibold tracking-tight">Northbridge</span>
          <span className="text-sm text-muted">Prior Authorization Copilot</span>
        </Link>
        <nav className="flex gap-1" aria-label="Main">
          {LINKS.map((l) => {
            const active = l.match(path);
            return (
              <Link
                key={l.href}
                href={l.href}
                aria-current={active ? "page" : undefined}
                className={`rounded-lg px-3 py-1.5 text-sm ${active ? "bg-surface-2 font-medium text-ink" : "text-ink-2 hover:bg-surface-2"}`}
              >
                {l.label}
              </Link>
            );
          })}
        </nav>
        <p className="ml-auto text-xs text-muted">Synthetic data only. Assists reviewers; never decides coverage.</p>
      </div>
    </header>
  );
}
