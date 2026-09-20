import { DISPATCH_LABEL, REVIEW_LABEL, STATUS } from "@/lib/labels";
import type { CaseView } from "@/lib/types";
import { Card, Notice, Pill } from "./ui";

/** What happened after a person decided: their decision, what was sent out, and the final document. */
export function Outcome({ view }: { view: CaseView }) {
  const s = STATUS[view.status];
  const d = view.dispatch;
  const dl = d ? DISPATCH_LABEL[d.status] ?? { label: d.status, tone: "neutral" as const } : null;
  return (
    <Card title="Decision" aside={view.review ? REVIEW_LABEL[view.review.action] : undefined}>
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <Pill tone={s.tone} icon={view.status === "rejected" ? "cross" : "check"}>
            {s.label}
          </Pill>
          {view.review ? <span className="text-sm text-ink-2">by {view.review.reviewer}</span> : null}
        </div>
        {view.review?.notes ? <p className="text-sm text-ink-2">“{view.review.notes}”</p> : null}

        {d && dl ? (
          <Notice tone={dl.tone === "neutral" ? "neutral" : dl.tone} title={`Sent out: ${dl.label}`}>
            {d.reference ? <span className="font-mono text-xs">{d.reference}</span> : null}
            {d.reason ? <span>{d.reason}</span> : null}
            {d.error ? <span>{d.error}</span> : null}
          </Notice>
        ) : null}

        {view.final_document ? (
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-muted">Final document</p>
            <pre className="mt-1 max-h-[26rem] overflow-auto whitespace-pre-wrap rounded-lg bg-surface-2 p-3 font-sans text-sm leading-relaxed">
              {view.final_document}
            </pre>
          </div>
        ) : null}
      </div>
    </Card>
  );
}
