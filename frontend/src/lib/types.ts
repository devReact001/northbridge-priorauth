// Shapes the FastAPI backend returns. They mirror build_packet() and view_from_state() in the workflow code.

export type Recommendation =
  | "likely_meets"
  | "needs_more_info"
  | "likely_not_meets"
  | "no_applicable_policy";

export type CaseStatus =
  | "in_progress"
  | "awaiting_review"
  | "approved"
  | "approved_with_edits"
  | "rejected"
  | "failed";

export type ReqStatus = "met" | "not_met" | "unclear" | "not_applicable";
export type DraftKind = "submission_letter" | "information_request" | "denial_risk_memo";
export type ReviewAction = "approve" | "edit" | "reject";

export interface Requirement {
  requirement: string;
  status: ReqStatus;
  /** Verbatim quotes that back the status. */
  quotes: string[];
  /** Where each quote was found: "note", or a chart reference such as "Observation/obs-2". */
  sources: string[];
}

export interface Pathway {
  name: string;
  cite: string;
  status: ReqStatus;
  requirements: Requirement[];
}

export interface Exclusion {
  policy_id: string;
  section: string;
  reason: string;
  basis: "documented" | "missing_documentation";
  source_quote: string;
  source: string | null;
}

export interface ChartFact {
  ref: string;
  date: string | null;
  text: string;
}

export interface ChartLookup {
  status: "ok" | "no_records" | "patient_not_found" | "skipped" | "error";
  detail: string;
  tool_calls: { tool: string }[];
  facts: ChartFact[];
}

export interface Draft {
  kind: DraftKind;
  subject: string;
  body: string;
  warnings: string[];
}

export interface Packet {
  case_id: string;
  escalation_reason: string | null;
  intake: {
    requested_procedure: string | null;
    procedure_code: string | null;
    diagnoses: string[];
    confidence: number | null;
    missing_information: string[];
    unverified_quotes: string[];
  };
  recommendation: Recommendation | null;
  policy_id: string | null;
  draft: Draft | null;
  allowed_actions: ReviewAction[];
  ehr?: ChartLookup;
  summary?: string;
  guardrail_notes?: string[];
  pathways?: Pathway[];
  exclusions_triggered?: Exclusion[];
  general_requirements?: { requirement: string; status: ReqStatus }[];
}

export interface TraceEvent {
  node: string;
  ts: string | null;
  latency_ms: number;
  input_tokens: number;
  output_tokens: number;
  detail: Record<string, unknown>;
}

export interface Dispatch {
  status: string;
  tool?: string;
  reference?: string | null;
  reason?: string;
  error?: string;
}

export interface CaseView {
  case_id: string;
  status: CaseStatus;
  recommendation: Recommendation | null;
  packet: Packet | null;
  review: { action: ReviewAction; reviewer: string; notes: string } | null;
  final_document: string | null;
  dispatch: Dispatch | null;
  note_text: string | null;
  request_date: string | null;
  source_name: string | null;
  resumable: boolean;
  trace: TraceEvent[];
  error?: string;
}

export interface CaseSummary {
  case_id: string;
  status: CaseStatus;
  recommendation: Recommendation | null;
  source_name: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface Sample {
  name: string;
  text: string;
  suggested_request_date: string | null;
}

export interface ReviewInput {
  action: ReviewAction;
  reviewer: string;
  notes: string;
  edited_letter?: string;
}

export interface LatencyRow {
  count: number;
  p50_ms: number;
  p95_ms: number;
  mean_ms: number;
  input_tokens: number;
  output_tokens: number;
}

export interface Metrics {
  days: number;
  total_cases: number;
  outcomes: { by_status: Record<string, number>; by_recommendation: Record<string, number> };
  review: {
    decided: number;
    approve: number;
    edit: number;
    reject: number;
    change_rate: number | null;
    by_recommendation: Record<string, { approve: number; edit: number; reject: number }>;
  };
  latency: Record<string, LatencyRow>;
  end_to_end: { count: number; p50_ms: number | null; p95_ms: number | null };
  tokens: { input: number; output: number };
  guardrails: {
    cases_with_any: number;
    rate: number | null;
    by_kind: Record<string, number>;
    intake_unverified_quote_cases: number;
  };
  ehr: { by_status: Record<string, number>; avg_facts: number | null };
  dispatch: { by_status: Record<string, number>; blocked_reasons: Record<string, number> };
  per_day: { date: string; cases: number }[];
}
