"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api } from "@/lib/api";
import { today } from "@/lib/format";
import { Button, Card, Notice, Spinner } from "./ui";

export function NewCaseForm() {
  const router = useRouter();
  const samples = useQuery({ queryKey: ["samples"], queryFn: api.samples, staleTime: Infinity });
  const [text, setText] = useState("");
  const [source, setSource] = useState("");
  const [date, setDate] = useState(today());
  const [picked, setPicked] = useState("");

  const start = useMutation({
    mutationFn: () => api.createCase({ text, source_name: source || undefined, request_date: date }),
    onSuccess: (res) => router.push(`/cases/${res.case_id}`),
  });

  function pick(name: string) {
    setPicked(name);
    const s = samples.data?.samples.find((x) => x.name === name);
    if (!s) return;
    setText(s.text);
    setSource(s.name);
    if (s.suggested_request_date) setDate(s.suggested_request_date);
  }

  const tooShort = text.trim().length < 20;

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">New case</h1>
        <p className="mt-1 text-sm text-ink-2">
          Paste a synthetic clinical note, or start from a sample. The workflow reads the note, finds the payer
          policy, looks up the patient’s chart, checks the criteria and drafts a document. It then waits for you.
        </p>
      </div>

      <Notice tone="warn" title="Synthetic data only">
        Do not paste real patient information. This is a portfolio project, not a clinical system.
      </Notice>

      <Card>
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (!tooShort) start.mutate();
          }}
        >
          <div className="grid gap-4 sm:grid-cols-[1fr_11rem]">
            <label className="block text-sm">
              <span className="mb-1 block font-medium">Start from a sample</span>
              <select
                value={picked}
                onChange={(e) => pick(e.target.value)}
                className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm"
                disabled={samples.isLoading}
              >
                <option value="">{samples.isError ? "Samples unavailable" : "Choose a sample note…"}</option>
                {samples.data?.samples.map((s) => (
                  <option key={s.name} value={s.name}>
                    {s.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-sm">
              <span className="mb-1 block font-medium">Request date</span>
              <input
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
                required
                className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm"
              />
            </label>
          </div>

          <label className="block text-sm">
            <span className="mb-1 block font-medium">Clinical note</span>
            <textarea
              value={text}
              onChange={(e) => {
                setText(e.target.value);
                setPicked("");
              }}
              rows={16}
              placeholder="Paste a synthetic clinical note…"
              className="w-full rounded-lg border border-line bg-surface px-3 py-2 font-mono text-[13px] leading-relaxed"
            />
            <span className="mt-1 block text-xs text-muted">
              The request date matters: policies require a note no older than 60 days before it.
            </span>
          </label>

          {start.isError ? (
            <Notice tone="crit" title="Could not start the case">
              {(start.error as Error).message}
            </Notice>
          ) : null}

          <div className="flex items-center justify-between gap-3">
            <p className="text-xs text-muted">A run takes about a minute. You will see each step as it finishes.</p>
            <Button type="submit" variant="primary" disabled={tooShort || start.isPending}>
              {start.isPending ? <Spinner /> : null}
              Start case
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}
