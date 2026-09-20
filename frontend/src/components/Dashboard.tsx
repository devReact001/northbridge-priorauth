"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { compact, percent, seconds } from "@/lib/format";
import {
  BLOCK_REASON_LABEL,
  DISPATCH_LABEL,
  EHR_LABEL,
  GUARDRAIL_LABEL,
  RECOMMENDATION,
  STEP_LABEL,
} from "@/lib/labels";
import type { Metrics } from "@/lib/types";
import { Columns, GroupedBars, HBars, S1, S2, S3, StackedBars, StatusRows, TableView, Tile } from "./Charts";
import { Card, Empty, Notice, Spinner } from "./ui";

const RANGES = [7, 30, 90];
const STEP_ORDER = ["intake", "ehr", "assess", "draft", "dispatch"];

const LATENCY_SERIES = [
  { key: "p50", label: "Median (p50)", className: S1 },
  { key: "p95", label: "Slowest 1 in 20 (p95)", className: S2 },
];
const REVIEW_SERIES = [
  { key: "approve", label: "Approved as drafted", className: S1 },
  { key: "edit", label: "Edited", className: S2 },
  { key: "reject", label: "Rejected", className: S3 },
];

function recLabel(key: string) {
  return (RECOMMENDATION as Record<string, { label: string }>)[key]?.label ?? key;
}

export function Dashboard() {
  const [days, setDays] = useState(30);
  const query = useQuery({ queryKey: ["metrics", days], queryFn: () => api.metrics(days), refetchInterval: 30_000 });
  const m = query.data;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Dashboard</h1>
          <p className="mt-1 max-w-2xl text-sm text-ink-2">
            How the copilot behaves: what it recommends, what reviewers do with it, where time goes, and which
            safeguards stepped in. Computed from saved cases and their step-by-step traces.
          </p>
        </div>
        <div className="flex gap-1" role="group" aria-label="Time range">
          {RANGES.map((r) => (
            <button
              key={r}
              onClick={() => setDays(r)}
              aria-pressed={days === r}
              className={`rounded-full border px-3 py-1 text-sm ${
                days === r ? "border-ink bg-ink text-bg" : "border-line bg-surface text-ink-2 hover:bg-surface-2"
              }`}
            >
              {r} days
            </button>
          ))}
        </div>
      </div>

      {query.isLoading ? (
        <div className="flex items-center gap-2 py-12 text-sm text-muted">
          <Spinner /> Loading metrics…
        </div>
      ) : query.isError ? (
        <Notice tone="crit" title="Could not load metrics">
          {(query.error as Error).message}
        </Notice>
      ) : m && m.total_cases === 0 ? (
        <Empty title={`No cases in the last ${days} days`}>Run a case from the review queue and its numbers appear here.</Empty>
      ) : m ? (
        <Body m={m} />
      ) : null}
    </div>
  );
}

function Body({ m }: { m: Metrics }) {
  const recRows = Object.entries(m.outcomes.by_recommendation)
    .sort((a, b) => b[1] - a[1])
    .map(([k, v]) => ({ label: recLabel(k), value: v }));

  const reviewRows = Object.entries(m.review.by_recommendation).map(([k, v]) => ({
    label: recLabel(k),
    values: v as unknown as Record<string, number>,
  }));

  const latencyRows = STEP_ORDER.filter((s) => m.latency[s]).map((s) => ({
    label: STEP_LABEL[s] ?? s,
    values: { p50: m.latency[s].p50_ms, p95: m.latency[s].p95_ms } as Record<string, number | null>,
  }));

  const guardRows = Object.entries(m.guardrails.by_kind).map(([k, v]) => ({ label: GUARDRAIL_LABEL[k] ?? k, value: v }));
  const ehrRows = Object.entries(m.ehr.by_status).map(([k, v]) => ({
    label: EHR_LABEL[k]?.label ?? k,
    count: v,
    tone: EHR_LABEL[k]?.tone ?? ("neutral" as const),
  }));
  const dispatchRows = Object.entries(m.dispatch.by_status).map(([k, v]) => ({
    label: DISPATCH_LABEL[k]?.label ?? k,
    count: v,
    tone: DISPATCH_LABEL[k]?.tone ?? ("neutral" as const),
  }));
  const blockedRows = Object.entries(m.dispatch.blocked_reasons).map(([k, v]) => ({ label: BLOCK_REASON_LABEL[k] ?? k, value: v }));

  return (
    <>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Tile label="Cases" value={m.total_cases} sub={`${m.review.decided} decided by a person`} />
        <Tile
          label="Reviewers changed the answer"
          value={percent(m.review.change_rate)}
          sub={m.review.decided ? `${m.review.edit} edited, ${m.review.reject} rejected of ${m.review.decided}` : "no decisions yet"}
        />
        <Tile
          label="Median time to review-ready"
          value={seconds(m.end_to_end.p50_ms)}
          sub={`slowest 1 in 20: ${seconds(m.end_to_end.p95_ms)}`}
        />
        <Tile
          label="Cases a guardrail acted on"
          value={percent(m.guardrails.rate)}
          sub={`${m.guardrails.cases_with_any} of ${m.total_cases} cases`}
        />
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="What the copilot recommended" aside="computed by code from the evidence">
          <HBars rows={recRows} />
          <TableView columns={["Recommendation", "Cases"]} rows={recRows.map((r) => [r.label, r.value])} />
        </Card>

        <Card title="What reviewers did with it" aside="by recommendation">
          {reviewRows.length > 0 ? (
            <>
              <StackedBars rows={reviewRows} series={REVIEW_SERIES} />
              <p className="mt-3 text-xs text-muted">
                Edits and rejections are the human overruling or fixing the machine. A high rate on one recommendation
                shows where to improve.
              </p>
              <TableView
                columns={["Recommendation", "Approved", "Edited", "Rejected"]}
                rows={reviewRows.map((r) => [r.label, r.values.approve, r.values.edit, r.values.reject])}
              />
            </>
          ) : (
            <p className="text-sm text-muted">No decisions recorded yet.</p>
          )}
        </Card>
      </div>

      <Card title="Where the time goes" aside="per step, in seconds">
        <GroupedBars rows={latencyRows} series={LATENCY_SERIES} format={seconds} />
        <p className="mt-3 text-xs text-muted">
          Waiting for a person is not counted. {compact(m.tokens.input)} tokens in and {compact(m.tokens.output)} out across all cases.
        </p>
        <TableView
          columns={["Step", "Runs", "p50", "p95", "Tokens in", "Tokens out"]}
          rows={STEP_ORDER.filter((s) => m.latency[s]).map((s) => [
            STEP_LABEL[s] ?? s,
            m.latency[s].count,
            seconds(m.latency[s].p50_ms),
            seconds(m.latency[s].p95_ms),
            m.latency[s].input_tokens,
            m.latency[s].output_tokens,
          ])}
        />
      </Card>

      <Card title="Safeguards that stepped in" aside="how often, across cases">
        {guardRows.length > 0 ? (
          <>
            <HBars rows={guardRows} />
            <p className="mt-3 text-xs text-muted">
              Each of these is a model mistake that code contained before it reached a decision: a quote that was not in
              the note, a prerequisite mistaken for an approval route, an answer cut off at the token limit.
              {m.guardrails.intake_unverified_quote_cases > 0
                ? ` The first reading also produced unverifiable quotes in ${m.guardrails.intake_unverified_quote_cases} case(s).`
                : ""}
            </p>
            <TableView columns={["Safeguard", "Cases"]} rows={guardRows.map((r) => [r.label, r.value])} />
          </>
        ) : (
          <p className="text-sm text-muted">No guardrail needed to act in this period.</p>
        )}
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card title="Chart lookup" aside={m.ehr.avg_facts != null ? `${m.ehr.avg_facts} facts per successful lookup` : undefined}>
          {ehrRows.length > 0 ? (
            <>
              <StatusRows rows={ehrRows} />
              <TableView columns={["Outcome", "Cases"]} rows={ehrRows.map((r) => [r.label, r.count])} />
            </>
          ) : (
            <p className="text-sm text-muted">No chart lookups in this period.</p>
          )}
        </Card>

        <Card title="What was sent out" aside="only after a person approved">
          {dispatchRows.length > 0 ? (
            <>
              <StatusRows rows={dispatchRows} />
              {blockedRows.length > 0 ? (
                <div className="mt-4">
                  <p className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">Why some were blocked</p>
                  <HBars rows={blockedRows} mark={S2} />
                </div>
              ) : null}
              <TableView columns={["Outcome", "Cases"]} rows={dispatchRows.map((r) => [r.label, r.count])} />
            </>
          ) : (
            <p className="text-sm text-muted">Nothing has been decided yet.</p>
          )}
        </Card>
      </div>

      {m.per_day.length > 0 ? (
        <Card title="Cases per day">
          <Columns points={m.per_day.map((d) => ({ label: d.date, value: d.cases }))} />
          <TableView columns={["Date", "Cases"]} rows={m.per_day.map((d) => [d.date, d.cases])} />
        </Card>
      ) : null}
    </>
  );
}
