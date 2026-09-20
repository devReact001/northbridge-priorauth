import { Icon, Pill } from "./ui";
import { REQ_STATUS } from "@/lib/labels";
import type { Exclusion, Pathway, ReqStatus, Requirement } from "@/lib/types";

/** Where a quote was found: the clinical note, or a resource in the patient's chart. */
export function SourceTag({ source }: { source: string }) {
  const note = source === "note";
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 font-mono text-[11px] ${
        note ? "bg-surface-2 text-ink-2" : "bg-warn-bg text-warn"
      }`}
      title={note ? "Quoted from the clinical note" : "Read from the patient's chart"}
    >
      <Icon name={note ? "note" : "chart"} className="h-3 w-3" />
      {note ? "Note" : `Chart · ${source}`}
    </span>
  );
}

export function StatusMark({ status }: { status: ReqStatus }) {
  const s = REQ_STATUS[status];
  const tone = { good: "text-good", crit: "text-crit", warn: "text-warn", neutral: "text-muted" }[s.tone];
  return (
    <span className={`mt-0.5 inline-flex w-[5.5rem] shrink-0 items-center gap-1 text-xs font-medium ${tone}`}>
      <Icon name={s.icon} className="h-3.5 w-3.5" />
      {s.label}
    </span>
  );
}

function RequirementRow({ r }: { r: Requirement }) {
  return (
    <li className="flex gap-2 py-2">
      <StatusMark status={r.status} />
      <div className="min-w-0 flex-1">
        <p className="text-sm text-ink">{r.requirement}</p>
        {r.quotes.length > 0 ? (
          <ul className="mt-1.5 space-y-1.5">
            {r.quotes.map((q, i) => (
              <li key={i} className="flex flex-wrap items-start gap-x-2 gap-y-1">
                <SourceTag source={r.sources[i] ?? "note"} />
                <blockquote className="min-w-0 flex-1 border-l-2 border-line pl-2 text-[13px] leading-snug text-ink-2">
                  {q}
                </blockquote>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </li>
  );
}

const ORDER: Record<ReqStatus, number> = { met: 0, unclear: 1, not_met: 2, not_applicable: 3 };

export function PathwayList({ pathways }: { pathways: Pathway[] }) {
  const sorted = [...pathways].sort((a, b) => ORDER[a.status] - ORDER[b.status]);
  return (
    <div className="space-y-2">
      {sorted.map((p) => {
        const s = REQ_STATUS[p.status];
        const met = p.requirements.filter((r) => r.status === "met").length;
        return (
          <details key={p.cite} open={p.status === "met" || p.status === "unclear"} className="group rounded-lg border border-line">
            <summary className="flex cursor-pointer list-none flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2.5 hover:bg-surface-2">
              <Icon name="chevron" className="h-4 w-4 shrink-0 text-muted transition group-open:rotate-90" />
              <span className="min-w-0 flex-1 text-sm font-medium">
                {p.name} <span className="ml-1 font-mono text-xs font-normal text-muted">{p.cite}</span>
              </span>
              <span className="tabular text-xs text-muted">
                {met}/{p.requirements.length} met
              </span>
              <Pill tone={s.tone} icon={s.icon}>
                {s.label}
              </Pill>
            </summary>
            <ul className="divide-y divide-line border-t border-line px-3">
              {p.requirements.map((r, i) => (
                <RequirementRow key={i} r={r} />
              ))}
            </ul>
          </details>
        );
      })}
    </div>
  );
}

export function GeneralRequirements({ items }: { items: { requirement: string; status: ReqStatus }[] }) {
  const open = items.filter((r) => r.status !== "met" && r.status !== "not_applicable");
  return (
    <details open={open.length > 0} className="group rounded-lg border border-line">
      <summary className="flex cursor-pointer list-none items-center gap-3 px-3 py-2.5 hover:bg-surface-2">
        <Icon name="chevron" className="h-4 w-4 shrink-0 text-muted transition group-open:rotate-90" />
        <span className="flex-1 text-sm font-medium">General requirements</span>
        <span className="tabular text-xs text-muted">
          {items.filter((r) => r.status === "met").length}/{items.length} met
          {open.length > 0 ? ` · ${open.length} open` : ""}
        </span>
      </summary>
      <ul className="divide-y divide-line border-t border-line px-3">
        {[...items]
          .sort((a, b) => ORDER[b.status] - ORDER[a.status])
          .map((r, i) => (
            <li key={i} className="flex gap-2 py-2">
              <StatusMark status={r.status} />
              <p className="text-sm text-ink">{r.requirement}</p>
            </li>
          ))}
      </ul>
    </details>
  );
}

export function Exclusions({ items }: { items: Exclusion[] }) {
  return (
    <ul className="space-y-2">
      {items.map((e, i) => {
        const documented = e.basis === "documented";
        return (
          <li key={i} className="rounded-lg border border-line p-3">
            <div className="flex flex-wrap items-center gap-2">
              <Pill tone={documented ? "crit" : "warn"} icon={documented ? "cross" : "question"}>
                {documented ? "Documented exclusion" : "Documentation gap"}
              </Pill>
              <span className="font-mono text-xs text-muted">
                {e.policy_id} section {e.section}
              </span>
            </div>
            <p className="mt-1.5 text-sm">{e.reason}</p>
            {e.source_quote ? (
              <div className="mt-1.5 flex flex-wrap items-start gap-x-2 gap-y-1">
                <SourceTag source={e.source ?? "note"} />
                <blockquote className="min-w-0 flex-1 border-l-2 border-line pl-2 text-[13px] text-ink-2">{e.source_quote}</blockquote>
              </div>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}
