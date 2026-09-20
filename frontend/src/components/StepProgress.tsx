import { useEffect, useState } from "react";
import { seconds } from "@/lib/format";
import { PIPELINE, STEP_LABEL } from "@/lib/labels";
import type { TraceEvent } from "@/lib/types";
import { Icon, Spinner } from "./ui";

/** Whole seconds since `since`, ticking once a second, so the step that is running shows it is alive. */
function useElapsed(since: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  return Math.max(0, Math.floor((now - since) / 1000));
}

/** Shown while a case runs. Steps tick off as their trace events arrive from the backend. */
export function StepProgress({ trace }: { trace: TraceEvent[] }) {
  const done = new Map(trace.map((e) => [e.node, e]));
  // A step starts when the previous one finishes, so its clock starts at the last event; before the first event
  // it starts when this panel appeared.
  const [mounted] = useState(() => Date.now());
  const last = trace.length ? Date.parse(trace[trace.length - 1].ts ?? "") : NaN;
  const elapsed = useElapsed(Number.isNaN(last) ? mounted : last);
  // The EHR step is skipped when the chart source is off; do not wait on a step that will not happen.
  const steps = PIPELINE.filter((s) => s !== "human_review");
  const current = steps.find((s) => !done.has(s) && !(s === "ehr" && done.has("assess")));
  return (
    <ol className="space-y-2">
      {steps.map((s) => {
        const e = done.get(s);
        const skipped = s === "ehr" && !e && done.has("assess");
        const active = s === current;
        return (
          <li key={s} className="flex items-center gap-3 text-sm">
            <span
              className={`flex h-6 w-6 items-center justify-center rounded-full ${
                e ? "bg-good-bg text-good" : active ? "bg-surface-2 text-ink" : "bg-surface-2 text-muted"
              }`}
            >
              {e ? <Icon name="check" className="h-3.5 w-3.5" /> : active ? <Spinner className="h-3.5 w-3.5" /> : <Icon name="dash" className="h-3.5 w-3.5" />}
            </span>
            <span className={e || active ? "text-ink" : "text-muted"}>{STEP_LABEL[s]}</span>
            {skipped ? <span className="text-xs text-muted">skipped</span> : null}
            {e?.latency_ms ? <span className="tabular ml-auto text-xs text-muted">{seconds(e.latency_ms)}</span> : null}
            {active ? <span className="tabular ml-auto text-xs text-muted">{elapsed} s</span> : null}
          </li>
        );
      })}
    </ol>
  );
}
