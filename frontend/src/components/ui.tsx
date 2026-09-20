import type { ButtonHTMLAttributes, ReactNode } from "react";
import type { Tone } from "@/lib/labels";

export const TONE: Record<Tone, string> = {
  good: "bg-good-bg text-good",
  warn: "bg-warn-bg text-warn",
  crit: "bg-crit-bg text-crit",
  neutral: "bg-surface-2 text-ink-2",
};

export type IconName = "check" | "cross" | "question" | "dash" | "chart" | "note" | "clock" | "warn" | "chevron";

/** Status is never colour alone: every pill and row carries one of these shapes as well as a word. */
export function Icon({ name, className = "h-4 w-4" }: { name: IconName | string; className?: string }) {
  const common = {
    className,
    viewBox: "0 0 16 16",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.75,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
  };
  switch (name) {
    case "check":
      return (
        <svg {...common}>
          <path d="M3 8.5l3.2 3L13 4.5" />
        </svg>
      );
    case "cross":
      return (
        <svg {...common}>
          <path d="M4 4l8 8M12 4l-8 8" />
        </svg>
      );
    case "question":
      return (
        <svg {...common}>
          <path d="M6 6.2a2 2 0 1 1 2.9 1.8c-.6.3-.9.8-.9 1.4" />
          <path d="M8 12h.01" />
        </svg>
      );
    case "dash":
      return (
        <svg {...common}>
          <path d="M4 8h8" />
        </svg>
      );
    case "warn":
      return (
        <svg {...common}>
          <path d="M8 2.5l6 10.5H2z" />
          <path d="M8 6.5v3M8 11.5h.01" />
        </svg>
      );
    case "clock":
      return (
        <svg {...common}>
          <circle cx="8" cy="8" r="5.5" />
          <path d="M8 5v3.2l2 1.2" />
        </svg>
      );
    case "chart":
      return (
        <svg {...common}>
          <path d="M3 13V6M8 13V3M13 13V9" />
        </svg>
      );
    case "note":
      return (
        <svg {...common}>
          <path d="M4 2.5h6l2.5 2.5v8.5H4z" />
          <path d="M6 8h4M6 10.5h4" />
        </svg>
      );
    case "chevron":
      return (
        <svg {...common}>
          <path d="M6 3.5L10.5 8 6 12.5" />
        </svg>
      );
    default:
      return null;
  }
}

export function Pill({ tone, icon, children }: { tone: Tone; icon?: IconName | string; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium ${TONE[tone]}`}>
      {icon ? <Icon name={icon} className="h-3.5 w-3.5" /> : null}
      {children}
    </span>
  );
}

export function Card({
  title,
  aside,
  children,
  className = "",
  id,
}: {
  title?: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <section id={id} className={`rounded-xl border border-line bg-surface ${className}`}>
      {title ? (
        <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
          <h2 className="text-sm font-semibold text-ink">{title}</h2>
          {aside ? <div className="text-xs text-muted">{aside}</div> : null}
        </header>
      ) : null}
      <div className="p-4">{children}</div>
    </section>
  );
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" };

export function Button({ variant = "secondary", className = "", ...rest }: ButtonProps) {
  const styles = {
    primary: "bg-brand text-brand-fg hover:opacity-90",
    secondary: "border border-line bg-surface text-ink hover:bg-surface-2",
    danger: "border border-line bg-surface text-crit hover:bg-crit-bg",
  }[variant];
  return (
    <button
      {...rest}
      className={`inline-flex items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${styles} ${className}`}
    />
  );
}

export function Spinner({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg className={`spin ${className}`} viewBox="0 0 16 16" fill="none" aria-hidden>
      <circle cx="8" cy="8" r="6" stroke="currentColor" strokeOpacity="0.25" strokeWidth="2" />
      <path d="M14 8a6 6 0 0 0-6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

export function Notice({ tone = "neutral", title, children }: { tone?: Tone; title?: string; children?: ReactNode }) {
  const icon = tone === "crit" ? "cross" : tone === "warn" ? "warn" : tone === "good" ? "check" : "note";
  return (
    <div className={`flex gap-3 rounded-xl px-4 py-3 text-sm ${TONE[tone]}`} role={tone === "crit" ? "alert" : "status"}>
      <Icon name={icon} className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="min-w-0">
        {title ? <p className="font-medium">{title}</p> : null}
        {children ? <div className={title ? "mt-0.5 opacity-90" : ""}>{children}</div> : null}
      </div>
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-line px-6 py-12 text-center">
      <p className="text-sm font-medium text-ink">{title}</p>
      {children ? <div className="mx-auto mt-1 max-w-md text-sm text-muted">{children}</div> : null}
    </div>
  );
}
