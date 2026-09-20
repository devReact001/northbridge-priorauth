import { EHR_LABEL } from "@/lib/labels";
import type { ChartLookup } from "@/lib/types";
import { Pill } from "./ui";

/** The patient's chart facts, read through the read-only FHIR MCP server. Facts the assessment cited are marked. */
export function ChartPanel({ chart, cited }: { chart: ChartLookup; cited: Set<string> }) {
  const s = EHR_LABEL[chart.status] ?? { label: chart.status, tone: "neutral" as const };
  const tools = Array.from(new Set(chart.tool_calls.map((c) => c.tool)));
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Pill tone={s.tone} icon={s.tone === "good" ? "check" : s.tone === "crit" ? "cross" : "dash"}>
          {s.label}
        </Pill>
        <span className="tabular text-xs text-muted">{chart.facts.length} facts</span>
        {tools.length > 0 ? <span className="text-xs text-muted">via {tools.join(", ")}</span> : null}
      </div>
      {chart.detail && chart.status !== "ok" ? <p className="text-sm text-ink-2">{chart.detail}</p> : null}
      {chart.facts.length > 0 ? (
        <ul className="divide-y divide-line rounded-lg border border-line">
          {chart.facts.map((f) => {
            const used = cited.has(f.ref);
            return (
              <li key={f.ref} className="flex items-start gap-2 px-3 py-2">
                <span className="min-w-0 flex-1 text-[13px] leading-snug text-ink-2">{f.text}</span>
                {used ? (
                  <span className="shrink-0 rounded bg-good-bg px-1.5 py-0.5 text-[11px] font-medium text-good">Cited</span>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}
      <p className="text-xs text-muted">
        Read-only. Names and addresses are never pulled: only the fields a requirement needs.
      </p>
    </div>
  );
}
