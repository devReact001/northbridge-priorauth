import type { ReactNode } from "react";
import type { Tone } from "@/lib/labels";
import { Icon } from "./ui";

/* Chart building blocks, plain HTML + CSS on the validated palette (series slots 1-3, see globals.css).
   Bars are thin, square at the baseline and rounded (4px) at the data end; stacked segments are separated by a
   2px gap of the surface colour; values sit at the bar tip in text colours, never in the series colour; every
   chart has a table view so nothing depends on colour or on hovering. */

export interface Series {
  key: string;
  label: string;
  className: string; // Tailwind bg-* for the mark
}

export const S1 = "bg-s1";
export const S2 = "bg-s2";
export const S3 = "bg-s3";

export function Legend({ series }: { series: Series[] }) {
  if (series.length < 2) return null; // one series needs no legend: the chart title names it
  return (
    <ul className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-2">
      {series.map((s) => (
        <li key={s.key} className="flex items-center gap-1.5">
          <span className={`h-2.5 w-2.5 rounded-sm ${s.className}`} aria-hidden />
          {s.label}
        </li>
      ))}
    </ul>
  );
}

/** One series, one bar per row, value at the tip. */
export function HBars({
  rows,
  format = (n) => String(n),
  mark = S1,
}: {
  rows: { label: string; value: number; hint?: string }[];
  format?: (n: number) => string;
  mark?: string;
}) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <ul className="space-y-2.5">
      {rows.map((r) => (
        <li key={r.label} className="grid grid-cols-[minmax(7rem,13rem)_1fr] items-center gap-3" title={r.hint ?? `${r.label}: ${format(r.value)}`}>
          <span className="text-sm text-ink-2">{r.label}</span>
          <span className="flex items-center gap-2">
            <span
              className={`h-3.5 rounded-r-[4px] ${mark}`}
              style={{ width: `${Math.max(0.5, (r.value / max) * 82)}%`, minWidth: r.value > 0 ? 3 : 0 }}
            />
            <span className="tabular text-sm text-ink">{format(r.value)}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Two or more series side by side per row (for example p50 and p95 latency), separated by a 2px gap. */
export function GroupedBars({
  rows,
  series,
  format,
}: {
  rows: { label: string; values: Record<string, number | null> }[];
  series: Series[];
  format: (n: number) => string;
}) {
  const max = Math.max(1, ...rows.flatMap((r) => series.map((s) => r.values[s.key] ?? 0)));
  return (
    <div>
      <Legend series={series} />
      <ul className="space-y-3.5">
        {rows.map((r) => (
          <li key={r.label} className="grid grid-cols-[minmax(7rem,13rem)_1fr] items-center gap-3">
            <span className="text-sm text-ink-2">{r.label}</span>
            <div className="flex flex-col gap-[2px]">
              {series.map((s) => {
                const v = r.values[s.key];
                return (
                  <span key={s.key} className="flex items-center gap-2" title={`${r.label}, ${s.label}: ${v == null ? "–" : format(v)}`}>
                    <span
                      className={`h-3 rounded-r-[4px] ${s.className}`}
                      style={{ width: `${Math.max(0.5, ((v ?? 0) / max) * 80)}%`, minWidth: v ? 3 : 0 }}
                    />
                    <span className="tabular text-xs text-ink">{v == null ? "–" : format(v)}</span>
                  </span>
                );
              })}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** One stacked bar per row: the row total is the bar length, segments are separated by a 2px gap. */
export function StackedBars({
  rows,
  series,
}: {
  rows: { label: string; values: Record<string, number> }[];
  series: Series[];
}) {
  const totals = rows.map((r) => series.reduce((n, s) => n + (r.values[s.key] ?? 0), 0));
  const max = Math.max(1, ...totals);
  return (
    <div>
      <Legend series={series} />
      <ul className="space-y-3">
        {rows.map((r, i) => {
          const parts = series.filter((s) => (r.values[s.key] ?? 0) > 0);
          return (
            <li
              key={r.label}
              className="grid grid-cols-[minmax(7rem,13rem)_1fr] items-center gap-3"
              title={series.map((s) => `${s.label}: ${r.values[s.key] ?? 0}`).join(", ")}
            >
              <span className="text-sm text-ink-2">{r.label}</span>
              <span className="flex items-center gap-2">
                <span className="flex gap-[2px]" style={{ width: `${Math.max(1, (totals[i] / max) * 82)}%` }}>
                  {parts.map((s, k) => (
                    <span
                      key={s.key}
                      className={`h-3.5 ${s.className} ${k === parts.length - 1 ? "rounded-r-[4px]" : ""}`}
                      style={{ flexGrow: r.values[s.key], flexBasis: 0, minWidth: 3 }}
                    />
                  ))}
                </span>
                <span className="tabular text-sm text-ink">{totals[i]}</span>
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/** Columns over time, one series. The tallest column is labelled on its cap; the rest live in the tooltip and table. */
export function Columns({ points, unit = "cases" }: { points: { label: string; value: number }[]; unit?: string }) {
  const max = Math.max(1, ...points.map((p) => p.value));
  const peak = points.reduce((best, p, i) => (p.value > points[best].value ? i : best), 0);
  return (
    <div>
      <div className="flex h-36 items-end gap-[3px] border-b border-line" role="img" aria-label={`${unit} per day`}>
        {points.map((p, i) => (
          <div key={p.label} className="flex h-full min-w-0 flex-1 flex-col items-center justify-end" title={`${p.label}: ${p.value} ${unit}`}>
            {i === peak ? <span className="tabular mb-1 text-xs text-ink">{p.value}</span> : null}
            <span
              className="w-full max-w-[24px] rounded-t-[4px] bg-s1"
              style={{ height: `${Math.max(3, (p.value / max) * 82)}%` }}
            />
          </div>
        ))}
      </div>
      <div className="mt-1.5 flex justify-between text-xs text-muted">
        <span>{points[0]?.label}</span>
        <span>{points[points.length - 1]?.label}</span>
      </div>
    </div>
  );
}

/** Status rows: a shape and a word as well as a colour, with a count and a bar. */
export function StatusRows({
  rows,
}: {
  rows: { label: string; count: number; tone: Tone }[];
}) {
  const max = Math.max(1, ...rows.map((r) => r.count));
  const icon = { good: "check", warn: "warn", crit: "cross", neutral: "dash" } as const;
  const text = { good: "text-good", warn: "text-warn", crit: "text-crit", neutral: "text-muted" } as const;
  const fill = { good: "bg-good", warn: "bg-warn", crit: "bg-crit", neutral: "bg-muted" } as const;
  return (
    <ul className="space-y-2.5">
      {rows.map((r) => (
        <li key={r.label} className="grid grid-cols-[minmax(9rem,13rem)_1fr] items-center gap-3">
          <span className={`flex items-center gap-1.5 text-sm ${text[r.tone]}`}>
            <Icon name={icon[r.tone]} className="h-4 w-4" />
            <span className="text-ink-2">{r.label}</span>
          </span>
          <span className="flex items-center gap-2">
            <span className={`h-3.5 rounded-r-[4px] ${fill[r.tone]}`} style={{ width: `${Math.max(0.5, (r.count / max) * 80)}%`, minWidth: r.count > 0 ? 3 : 0 }} />
            <span className="tabular text-sm text-ink">{r.count}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

/** The chart's data as a table: the accessible view, and the place exact values live. */
export function TableView({ columns, rows }: { columns: string[]; rows: (string | number)[][] }) {
  return (
    <details className="mt-4 text-sm">
      <summary className="cursor-pointer text-xs text-muted hover:text-ink">Table view</summary>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="text-muted">
            <tr>
              {columns.map((c, i) => (
                <th key={c} className={`py-1 pr-3 font-medium ${i > 0 ? "text-right" : ""}`}>
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className="border-t border-line">
                {r.map((cell, j) => (
                  <td key={j} className={`tabular py-1 pr-3 ${j > 0 ? "text-right" : ""}`}>
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

export function Tile({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      <p className="text-sm text-ink-2">{label}</p>
      <p className="tabular mt-1 text-3xl font-semibold tracking-tight">{value}</p>
      {sub ? <p className="mt-1 text-xs text-muted">{sub}</p> : null}
    </div>
  );
}
