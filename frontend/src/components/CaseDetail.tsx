"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useMemo } from "react";
import { api } from "@/lib/api";
import { recommendation, STATUS } from "@/lib/labels";
import type { CaseView } from "@/lib/types";
import { ChartPanel } from "./ChartPanel";
import { DecisionPanel } from "./DecisionPanel";
import { Exclusions, GeneralRequirements, PathwayList } from "./Evidence";
import { NoteViewer } from "./NoteViewer";
import { Outcome } from "./Outcome";
import { StepProgress } from "./StepProgress";
import { TracePanel } from "./TracePanel";
import { Card, Notice, Pill, Spinner } from "./ui";

function evidenceIndex(view: CaseView) {
  const noteQuotes: string[] = [];
  const cited = new Set<string>();
  const add = (quote: string, source: string | null | undefined) => {
    if (!source || source === "note") noteQuotes.push(quote);
    else cited.add(source);
  };
  for (const p of view.packet?.pathways ?? [])
    for (const r of p.requirements) r.quotes.forEach((q, i) => add(q, r.sources[i] ?? "note"));
  for (const e of view.packet?.exclusions_triggered ?? []) if (e.source_quote) add(e.source_quote, e.source);
  return { noteQuotes, cited };
}

export function CaseDetail({ id }: { id: string }) {
  const query = useQuery({
    queryKey: ["case", id],
    queryFn: () => api.getCase(id),
    refetchInterval: (q) => (q.state.data?.status === "in_progress" ? 2_000 : false),
  });
  const view = query.data;
  const evidence = useMemo(() => (view ? evidenceIndex(view) : { noteQuotes: [], cited: new Set<string>() }), [view]);

  if (query.isLoading) {
    return (
      <div className="flex items-center gap-2 py-12 text-sm text-muted">
        <Spinner /> Loading case…
      </div>
    );
  }
  if (query.isError || !view) {
    return (
      <Notice tone="crit" title="Could not load this case">
        {(query.error as Error | null)?.message ?? "Unknown error"}
        <div className="mt-2">
          <Link href="/" className="underline">
            Back to the queue
          </Link>
        </div>
      </Notice>
    );
  }

  const status = STATUS[view.status];
  const rec = recommendation(view.recommendation);
  const packet = view.packet;
  const decided = view.status !== "awaiting_review" && view.status !== "in_progress" && view.status !== "failed";

  return (
    <div className="space-y-5">
      <div>
        <Link href="/" className="text-sm text-ink-2 hover:underline">
          ← Review queue
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-2">
          <h1 className="text-xl font-semibold tracking-tight">
            Case <span className="font-mono text-lg">{view.case_id}</span>
          </h1>
          <Pill tone={status.tone} icon={view.status === "in_progress" ? undefined : view.status === "awaiting_review" ? "clock" : view.status === "rejected" || view.status === "failed" ? "cross" : "check"}>
            {view.status === "in_progress" ? <Spinner className="h-3 w-3" /> : null}
            {status.label}
          </Pill>
          {view.source_name ? <span className="text-sm text-muted">{view.source_name}</span> : null}
          {view.request_date ? <span className="text-sm text-muted">request date {view.request_date}</span> : null}
        </div>
      </div>

      {view.status === "failed" ? (
        <Notice tone="crit" title="This case failed before it reached review">
          {view.error}
        </Notice>
      ) : null}

      {view.status === "in_progress" ? (
        <Card title="Working on it" aside="about a minute">
          <StepProgress trace={view.trace} />
          <p className="mt-4 text-xs text-muted">
            The page updates by itself. You can leave and come back: the case will be in the queue.
          </p>
        </Card>
      ) : null}

      {packet ? (
        <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,1fr)_28rem]">
          <div className="min-w-0 space-y-5">
            <Card>
              <div className="flex flex-wrap items-center gap-3">
                <span className="text-xs font-medium uppercase tracking-wide text-muted">Recommendation</span>
                <Pill tone={rec.tone} icon={rec.tone === "good" ? "check" : rec.tone === "crit" ? "cross" : rec.tone === "warn" ? "question" : "dash"}>
                  {rec.label}
                </Pill>
                {packet.policy_id ? <span className="font-mono text-xs text-muted">{packet.policy_id}</span> : null}
              </div>
              <p className="mt-2 text-xs text-muted">
                {rec.hint} A suggestion for you, not a decision: the recommendation is computed by code from the
                evidence, and you make the call.
              </p>
              {packet.summary ? <p className="mt-3 text-sm leading-relaxed">{packet.summary}</p> : null}
              <dl className="mt-4 grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
                <div>
                  <dt className="text-xs text-muted">Requested</dt>
                  <dd>
                    {packet.intake.requested_procedure ?? "–"}
                    {packet.intake.procedure_code ? ` (CPT ${packet.intake.procedure_code})` : ""}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs text-muted">Diagnoses</dt>
                  <dd>{packet.intake.diagnoses.join(", ") || "–"}</dd>
                </div>
                <div>
                  <dt className="text-xs text-muted">Extraction confidence</dt>
                  <dd className="tabular">{packet.intake.confidence ?? "–"}</dd>
                </div>
                {packet.intake.missing_information.length > 0 ? (
                  <div>
                    <dt className="text-xs text-muted">Missing from the note</dt>
                    <dd>{packet.intake.missing_information.join("; ")}</dd>
                  </div>
                ) : null}
              </dl>
              {packet.intake.unverified_quotes.length > 0 ? (
                <div className="mt-3">
                  <Notice tone="warn" title="Some extracted quotes are not in the note">
                    {packet.intake.unverified_quotes.length} quote(s) from the first reading could not be found
                    verbatim and were not relied on.
                  </Notice>
                </div>
              ) : null}
            </Card>

            {packet.pathways && packet.pathways.length > 0 ? (
              <Card title="Approval pathways" aside="quotes come from the note or the chart">
                <div className="space-y-2">
                  <PathwayList pathways={packet.pathways} />
                  {packet.general_requirements && packet.general_requirements.length > 0 ? (
                    <GeneralRequirements items={packet.general_requirements} />
                  ) : null}
                </div>
              </Card>
            ) : null}

            {packet.exclusions_triggered && packet.exclusions_triggered.length > 0 ? (
              <Card title="Exclusions" aside="a documented exclusion always needs a person">
                <Exclusions items={packet.exclusions_triggered} />
              </Card>
            ) : null}

            {packet.ehr ? (
              <Card title="Patient chart" aside="FHIR, read-only">
                <ChartPanel chart={packet.ehr} cited={evidence.cited} />
              </Card>
            ) : null}

            {packet.guardrail_notes && packet.guardrail_notes.length > 0 ? (
              <Card title="Guardrails that acted" aside="code that checked the model">
                <ul className="list-disc space-y-1 pl-5 text-sm text-ink-2">
                  {packet.guardrail_notes.map((n, i) => (
                    <li key={i}>{n}</li>
                  ))}
                </ul>
              </Card>
            ) : null}

            {view.note_text ? (
              <details className="group rounded-xl border border-line bg-surface">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3">
                  <span className="text-sm font-semibold">Clinical note</span>
                  <span className="text-xs text-muted">{evidence.noteQuotes.length} quotes highlighted</span>
                </summary>
                <div className="border-t border-line p-4">
                  <NoteViewer note={view.note_text} quotes={evidence.noteQuotes} />
                </div>
              </details>
            ) : null}

            {view.trace.length > 0 ? (
              <details className="group rounded-xl border border-line bg-surface">
                <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3">
                  <span className="text-sm font-semibold">Trace</span>
                  <span className="text-xs text-muted">time and tokens per step</span>
                </summary>
                <div className="border-t border-line p-4">
                  <TracePanel trace={view.trace} />
                </div>
              </details>
            ) : null}
          </div>

          <div className="min-w-0 lg:sticky lg:top-4">
            {decided ? <Outcome view={view} /> : view.status === "awaiting_review" ? <DecisionPanel key={view.case_id} view={view} /> : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
