"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { DRAFT_KIND } from "@/lib/labels";
import { placeholders } from "@/lib/text";
import type { CaseView, ReviewAction } from "@/lib/types";
import { Button, Card, Notice, Spinner } from "./ui";

const NAME_KEY = "northbridge.reviewer";

/** The one place a case gets decided. The document is always editable: unchanged means Approve, changed
 *  means Approve with edits. Blanks like [Ordering provider name] must be filled in before anything can be sent. */
export function DecisionPanel({ view }: { view: CaseView }) {
  const queryClient = useQueryClient();
  const draft = view.packet?.draft ?? null;
  const [text, setText] = useState(draft?.body ?? "");
  const [reviewer, setReviewer] = useState("");
  const [notes, setNotes] = useState("");
  const [confirmReject, setConfirmReject] = useState(false);

  useEffect(() => {
    try {
      setReviewer(window.localStorage.getItem(NAME_KEY) ?? "");
    } catch {
      /* storage can be blocked; the name field still works */
    }
  }, []);

  const decide = useMutation({
    mutationFn: (action: ReviewAction) =>
      api.review(view.case_id, {
        action,
        reviewer: reviewer.trim(),
        notes: notes.trim(),
        ...(action === "edit" ? { edited_letter: text } : {}),
      }),
    onSuccess: (updated) => {
      try {
        window.localStorage.setItem(NAME_KEY, reviewer.trim());
      } catch {
        /* ignore */
      }
      queryClient.setQueryData(["case", view.case_id], updated);
      queryClient.invalidateQueries({ queryKey: ["cases"] });
    },
  });

  const kind = draft ? DRAFT_KIND[draft.kind] : null;
  const internal = draft?.kind === "denial_risk_memo";
  const changed = draft ? text.trim() !== draft.body.trim() : true;
  const blanks = internal ? [] : placeholders(text);
  const hasName = reviewer.trim().length > 0;
  const hasText = text.trim().length > 0;
  const locked = !view.resumable || decide.isPending;
  const approveAction: ReviewAction = draft && !changed ? "approve" : "edit";
  const approveLabel = !draft ? "Submit my document" : changed ? "Approve with edits" : "Approve";
  const canApprove = hasName && hasText && blanks.length === 0 && !locked;

  return (
    <Card title="Your decision" aside={kind?.label}>
      <div className="space-y-4">
        {!view.resumable ? (
          <Notice tone="warn" title="This case can no longer be decided here">
            It was saved, but the API restarted and forgot the paused workflow. Run the backend with
            CHECKPOINTER=postgres so paused cases survive a restart.
          </Notice>
        ) : null}

        {view.packet?.escalation_reason ? (
          <Notice tone="warn" title="Escalated to a person">
            {view.packet.escalation_reason} There is no draft: write the document yourself, or reject.
          </Notice>
        ) : null}

        {draft?.subject ? (
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-muted">Subject</p>
            <p className="mt-0.5 text-sm">{draft.subject}</p>
          </div>
        ) : null}

        <label className="block">
          <span className="mb-1 flex items-center justify-between text-xs font-medium uppercase tracking-wide text-muted">
            {draft ? "Draft (editable)" : "Your document"}
            {draft && changed ? (
              <button type="button" className="normal-case text-brand hover:underline" onClick={() => setText(draft.body)}>
                Reset to draft
              </button>
            ) : null}
          </span>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            disabled={!view.resumable}
            rows={16}
            className="w-full rounded-lg border border-line bg-surface px-3 py-2 font-sans text-sm leading-relaxed"
            aria-describedby="doc-help"
          />
        </label>

        <div id="doc-help" className="space-y-2">
          {blanks.length > 0 ? (
            <Notice tone="warn" title={`${blanks.length} placeholder${blanks.length > 1 ? "s" : ""} to fill in`}>
              <span className="font-mono text-xs">{blanks.join("  ")}</span>
              <br />
              Replace them in the text above. A document with blanks cannot be approved or sent.
            </Notice>
          ) : null}
          {draft?.warnings?.length ? (
            <Notice tone="warn" title="Check before approving">
              <ul className="list-disc pl-4">
                {draft.warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </Notice>
          ) : null}
          {kind ? <p className="text-xs text-muted">{kind.effect}</p> : null}
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block text-sm">
            <span className="mb-1 block font-medium">Reviewer name</span>
            <input
              value={reviewer}
              onChange={(e) => setReviewer(e.target.value)}
              placeholder="Your name"
              className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm"
              autoComplete="name"
            />
          </label>
          <label className="block text-sm">
            <span className="mb-1 block font-medium">Notes (optional)</span>
            <input
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Why, if you changed or rejected it"
              className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm"
            />
          </label>
        </div>

        {decide.isError ? (
          <Notice tone="crit" title="Not accepted">
            {(decide.error as Error).message}
          </Notice>
        ) : null}

        <div className="flex flex-wrap items-center gap-2">
          <Button variant="primary" disabled={!canApprove} onClick={() => decide.mutate(approveAction)}>
            {decide.isPending && decide.variables !== "reject" ? <Spinner /> : null}
            {approveLabel}
          </Button>
          {!confirmReject ? (
            <Button variant="danger" disabled={locked} onClick={() => setConfirmReject(true)}>
              Reject
            </Button>
          ) : (
            <>
              <Button variant="danger" disabled={!hasName || locked} onClick={() => decide.mutate("reject")}>
                {decide.isPending && decide.variables === "reject" ? <Spinner /> : null}
                Confirm reject
              </Button>
              <Button onClick={() => setConfirmReject(false)}>Cancel</Button>
            </>
          )}
        </div>
        {!hasName && view.resumable ? <p className="text-xs text-muted">Enter your name to decide. It is recorded on everything sent out.</p> : null}
      </div>
    </Card>
  );
}
