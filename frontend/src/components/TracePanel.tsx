import { seconds, compact } from "@/lib/format";
import { STEP_LABEL } from "@/lib/labels";
import type { TraceEvent } from "@/lib/types";

function note(e: TraceEvent): string {
  const d = e.detail ?? {};
  switch (e.node) {
    case "intake":
      return d.unverified_quotes ? `${d.unverified_quotes} unverified quotes` : `confidence ${d.confidence ?? "–"}`;
    case "policy":
      return `${d.policy_id ?? "none"} · ${d.chunks ?? 0} sections`;
    case "ehr":
      return `${d.status ?? ""} · ${d.facts ?? 0} facts`;
    case "assess":
      return `${d.recommendation ?? ""}${d.guardrail_notes ? ` · ${d.guardrail_notes} guardrail notes` : ""}`;
    case "draft":
      return String(d.kind ?? "");
    case "human_review":
      return d.action ? `${d.action} by ${d.reviewer}` : "";
    case "finalize":
      return String(d.status ?? "");
    case "dispatch":
      return String(d.status ?? "") + (d.reference ? ` · ${d.reference}` : d.reason ? ` · ${d.reason}` : "");
    case "escalate":
      return String(d.reason ?? "");
    default:
      return "";
  }
}

export function TracePanel({ trace }: { trace: TraceEvent[] }) {
  const total = trace.reduce((n, e) => n + (e.node === "human_review" ? 0 : e.latency_ms), 0);
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[520px] text-left text-sm">
        <thead className="text-xs uppercase tracking-wide text-muted">
          <tr>
            <th className="py-1.5 pr-3 font-medium">Step</th>
            <th className="py-1.5 pr-3 text-right font-medium">Time</th>
            <th className="py-1.5 pr-3 text-right font-medium">Tokens in</th>
            <th className="py-1.5 pr-3 text-right font-medium">Tokens out</th>
            <th className="py-1.5 font-medium">Result</th>
          </tr>
        </thead>
        <tbody>
          {trace.map((e, i) => (
            <tr key={i} className="border-t border-line">
              <td className="py-1.5 pr-3">{STEP_LABEL[e.node] ?? e.node}</td>
              <td className="tabular py-1.5 pr-3 text-right text-ink-2">{e.latency_ms ? seconds(e.latency_ms) : "–"}</td>
              <td className="tabular py-1.5 pr-3 text-right text-ink-2">{e.input_tokens ? compact(e.input_tokens) : "–"}</td>
              <td className="tabular py-1.5 pr-3 text-right text-ink-2">{e.output_tokens ? compact(e.output_tokens) : "–"}</td>
              <td className="py-1.5 text-ink-2">{note(e)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t border-line font-medium">
            <td className="py-1.5 pr-3">Total (excluding human review)</td>
            <td className="tabular py-1.5 pr-3 text-right">{seconds(total)}</td>
            <td className="tabular py-1.5 pr-3 text-right">{compact(trace.reduce((n, e) => n + e.input_tokens, 0))}</td>
            <td className="tabular py-1.5 pr-3 text-right">{compact(trace.reduce((n, e) => n + e.output_tokens, 0))}</td>
            <td />
          </tr>
        </tfoot>
      </table>
    </div>
  );
}
