"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { api } from "@/lib/api";
import { shortDate } from "@/lib/format";
import { recommendation, STATUS } from "@/lib/labels";
import type { CaseStatus, CaseSummary } from "@/lib/types";
import { Button, Empty, Notice, Pill, Spinner } from "./ui";

const FILTERS: { value: string; label: string }[] = [
  { value: "", label: "All" },
  { value: "awaiting_review", label: "Awaiting review" },
  { value: "approved", label: "Approved" },
  { value: "approved_with_edits", label: "Approved with edits" },
  { value: "rejected", label: "Rejected" },
];

function StatusPill({ status }: { status: CaseStatus }) {
  const s = STATUS[status] ?? { label: status, tone: "neutral" as const };
  return (
    <Pill tone={s.tone} icon={status === "in_progress" ? undefined : status === "rejected" || status === "failed" ? "cross" : status === "awaiting_review" ? "clock" : "check"}>
      {status === "in_progress" ? <Spinner className="h-3 w-3" /> : null}
      {s.label}
    </Pill>
  );
}

export function CaseQueue() {
  const [filter, setFilter] = useState("");
  const query = useQuery({
    queryKey: ["cases", filter],
    queryFn: () => api.listCases(filter || undefined),
    refetchInterval: (q) => (q.state.data?.cases.some((c) => c.status === "in_progress") ? 3_000 : 10_000),
  });
  const cases: CaseSummary[] = query.data?.cases ?? [];
  const waiting = cases.filter((c) => c.status === "awaiting_review").length;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold tracking-tight">Review queue</h1>
          <p className="mt-1 text-sm text-ink-2">
            Every case stops here. Nothing is approved, sent or submitted until a person decides.
          </p>
        </div>
        <Link href="/cases/new">
          <Button variant="primary">New case</Button>
        </Link>
      </div>

      <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="Filter by status">
        {FILTERS.map((f) => (
          <button
            key={f.value}
            role="tab"
            aria-selected={filter === f.value}
            onClick={() => setFilter(f.value)}
            className={`rounded-full border px-3 py-1 text-sm ${
              filter === f.value ? "border-ink bg-ink text-bg" : "border-line bg-surface text-ink-2 hover:bg-surface-2"
            }`}
          >
            {f.label}
            {f.value === "awaiting_review" && waiting > 0 && filter !== f.value ? (
              <span className="ml-1.5 rounded-full bg-warn-bg px-1.5 text-xs text-warn">{waiting}</span>
            ) : null}
          </button>
        ))}
      </div>

      {query.isError ? (
        <Notice tone="crit" title="Could not load cases">
          {(query.error as Error).message}
        </Notice>
      ) : query.isLoading ? (
        <div className="flex items-center gap-2 py-12 text-sm text-muted">
          <Spinner /> Loading cases…
        </div>
      ) : cases.length === 0 ? (
        <Empty title={filter ? "No cases with this status" : "No cases yet"}>
          {filter ? "Try another filter." : "Start one from a sample note or paste your own synthetic note."}
        </Empty>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-line bg-surface">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead className="border-b border-line text-xs uppercase tracking-wide text-muted">
              <tr>
                <th className="px-4 py-2.5 font-medium">Case</th>
                <th className="px-4 py-2.5 font-medium">Source</th>
                <th className="px-4 py-2.5 font-medium">Recommendation</th>
                <th className="px-4 py-2.5 font-medium">Status</th>
                <th className="px-4 py-2.5 font-medium">Started</th>
              </tr>
            </thead>
            <tbody>
              {cases.map((c) => {
                const rec = recommendation(c.recommendation);
                const running = c.status === "in_progress";
                return (
                  <tr key={c.case_id} className="border-b border-line last:border-0 hover:bg-surface-2">
                    <td className="px-4 py-3">
                      <Link href={`/cases/${c.case_id}`} className="font-mono text-[13px] font-medium text-brand underline-offset-2 hover:underline">
                        {c.case_id}
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-ink-2">{c.source_name ?? "pasted note"}</td>
                    <td className="px-4 py-3">
                      {running ? <span className="text-muted">Working…</span> : <Pill tone={rec.tone}>{rec.label}</Pill>}
                    </td>
                    <td className="px-4 py-3">
                      <StatusPill status={c.status} />
                    </td>
                    <td className="tabular px-4 py-3 text-ink-2">{shortDate(c.created_at)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
