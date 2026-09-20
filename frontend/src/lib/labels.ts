import type { CaseStatus, DraftKind, ReqStatus, Recommendation } from "./types";

export type Tone = "good" | "warn" | "crit" | "neutral";

export const RECOMMENDATION: Record<Recommendation | "escalated", { label: string; tone: Tone; hint: string }> = {
  likely_meets: { label: "Likely meets", tone: "good", hint: "The evidence supports at least one approval pathway." },
  needs_more_info: { label: "Needs more information", tone: "warn", hint: "Something the policy needs is missing or unclear." },
  likely_not_meets: { label: "Unlikely to meet", tone: "crit", hint: "The record affirmatively fails the policy." },
  no_applicable_policy: { label: "No applicable policy", tone: "neutral", hint: "No payer policy covers this procedure." },
  escalated: { label: "Escalated", tone: "neutral", hint: "Sent straight to a person without an assessment." },
};

export function recommendation(r: Recommendation | null | undefined) {
  return RECOMMENDATION[r ?? "escalated"];
}

export const STATUS: Record<CaseStatus, { label: string; tone: Tone }> = {
  in_progress: { label: "Running", tone: "neutral" },
  awaiting_review: { label: "Awaiting review", tone: "warn" },
  approved: { label: "Approved", tone: "good" },
  approved_with_edits: { label: "Approved with edits", tone: "good" },
  rejected: { label: "Rejected", tone: "crit" },
  failed: { label: "Failed", tone: "crit" },
};

export const REQ_STATUS: Record<ReqStatus, { label: string; tone: Tone; icon: string }> = {
  met: { label: "Met", tone: "good", icon: "check" },
  not_met: { label: "Not met", tone: "crit", icon: "cross" },
  unclear: { label: "Unclear", tone: "warn", icon: "question" },
  not_applicable: { label: "Not applicable", tone: "neutral", icon: "dash" },
};

export const DRAFT_KIND: Record<DraftKind, { label: string; effect: string }> = {
  submission_letter: {
    label: "Submission letter",
    effect: "Approving submits this to the payer (in this project, a Claim written to the outbox).",
  },
  information_request: {
    label: "Information request",
    effect: "Approving sends this message to the ordering clinician.",
  },
  denial_risk_memo: {
    label: "Denial-risk memo",
    effect: "An internal memo. Nothing is sent outside.",
  },
};

export const PIPELINE = ["intake", "policy", "ehr", "assess", "draft", "human_review"] as const;

export const STEP_LABEL: Record<string, string> = {
  intake: "Read the note",
  policy: "Find the policy",
  ehr: "Look up the chart",
  assess: "Check the criteria",
  draft: "Draft the document",
  escalate: "Escalate",
  human_review: "Human review",
  finalize: "Finalize",
  dispatch: "Send out",
};

/** Guardrail kinds (see workflow/metrics.py) in plain words, for the dashboard. */
export const GUARDRAIL_LABEL: Record<string, string> = {
  quote_not_in_source: "Quote not found in the note or chart",
  met_without_quote: "“Met” with no verified quote",
  not_met_without_quote: "“Not met” with no verified quote",
  not_applicable_on_pathway: "“Not applicable” used on a pathway",
  prerequisite_as_pathway: "Prerequisite listed as a pathway",
  exclusion_wrong_section: "Exclusion from the wrong section",
  absence_exclusion: "Absence wording treated as a gap",
  exclusion_without_quote: "Exclusion without a verified quote",
  code_check_upgrade: "Code found in note or chart",
  truncated_retry: "Answer cut off, asked again",
  empty_pathways_retry: "No pathways, asked again",
  empty_pathways_default: "No pathways after retry",
  citation_not_in_policy: "Cited a section not provided",
  other: "Other",
};

export const EHR_LABEL: Record<string, { label: string; tone: Tone }> = {
  ok: { label: "Chart found", tone: "good" },
  no_records: { label: "No records", tone: "neutral" },
  patient_not_found: { label: "Patient not found", tone: "warn" },
  skipped: { label: "Skipped", tone: "neutral" },
  error: { label: "Error", tone: "crit" },
};

export const DISPATCH_LABEL: Record<string, { label: string; tone: Tone }> = {
  submitted: { label: "Submitted", tone: "good" },
  sent: { label: "Sent", tone: "good" },
  duplicate: { label: "Duplicate (already sent)", tone: "neutral" },
  skipped: { label: "Nothing to send", tone: "neutral" },
  blocked: { label: "Blocked", tone: "warn" },
  failed: { label: "Failed", tone: "crit" },
};

export const BLOCK_REASON_LABEL: Record<string, string> = {
  placeholders_left: "Placeholders left in the document",
  missing_codes: "Missing CPT or ICD-10 code",
  no_patient_id: "No patient identifier",
  other: "Other",
};

export const REVIEW_LABEL = { approve: "Approved as drafted", edit: "Edited", reject: "Rejected" } as const;
