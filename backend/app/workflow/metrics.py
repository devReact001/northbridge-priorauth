"""Numbers for the observability dashboard, computed from saved cases and their trace events.

Pure functions over plain dicts, so they are tested without a database. The SQL only fetches rows.

A saved case looks like:
    {"case_id", "created_at", "status", "recommendation", "state": {...}, "events": [{node, latency_ms, ...}]}
"""

import math
from collections import Counter, defaultdict
from typing import Any, Optional

# Steps that call a model or a service. `human_review` waits on a person, so it is never a latency.
TIMED_NODES = ["intake", "ehr", "assess", "draft", "dispatch"]

# A guardrail note is free text written by the code that fired it. This maps its wording to a stable kind,
# so the dashboard can count how often each safeguard acted.
GUARDRAIL_KINDS = [
    ("dropped a quote", "quote_not_in_source"),
    ("'met' has no verified quote", "met_without_quote"),
    ("'not_met' has no verified quote", "not_met_without_quote"),
    ("not_applicable' is not allowed", "not_applicable_on_pathway"),
    ("prerequisite is not an approval pathway", "prerequisite_as_pathway"),
    ("not an exclusions section", "exclusion_wrong_section"),
    ("wording is about absence", "absence_exclusion"),
    ("no verified quote in the note or EHR facts", "exclusion_without_quote"),
    ("upgraded to met", "code_check_upgrade"),
    ("cut off at the token limit", "truncated_retry"),
    ("returned no pathways at first", "empty_pathways_retry"),
    ("returned no pathways twice", "empty_pathways_default"),
    ("which was not in the policy provided", "citation_not_in_policy"),
]

REVIEW_ACTIONS = ["approve", "edit", "reject"]


def percentile(values: list[float], p: float) -> Optional[float]:
    """Nearest-rank percentile. None for an empty list."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(p / 100 * len(ordered)))
    return float(ordered[rank - 1])


def guardrail_kind(note: str) -> str:
    lowered = note.lower()
    for needle, kind in GUARDRAIL_KINDS:
        if needle.lower() in lowered:
            return kind
    return "other"


def dispatch_block_reason(reason: str) -> str:
    lowered = (reason or "").lower()
    if "placeholder" in lowered:
        return "placeholders_left"
    if "cpt" in lowered or "icd" in lowered:
        return "missing_codes"
    if "patient identifier" in lowered:
        return "no_patient_id"
    return "other"


def _rate(part: int, whole: int) -> Optional[float]:
    return round(part / whole, 3) if whole else None


def compute(cases: list[dict[str, Any]]) -> dict[str, Any]:
    by_status: Counter = Counter()
    by_rec: Counter = Counter()
    review_by_rec: dict[str, Counter] = defaultdict(Counter)
    review_totals: Counter = Counter()
    latencies: dict[str, list[float]] = defaultdict(list)
    tokens_in: Counter = Counter()
    tokens_out: Counter = Counter()
    end_to_end: list[float] = []
    guard_kinds: Counter = Counter()
    guard_cases = 0
    intake_unverified_cases = 0
    ehr_status: Counter = Counter()
    ehr_facts: list[int] = []
    dispatch_status: Counter = Counter()
    blocked: Counter = Counter()
    per_day: Counter = Counter()

    for c in cases:
        state = c.get("state") or {}
        by_status[c.get("status") or "unknown"] += 1
        rec = c.get("recommendation") or "escalated"
        by_rec[rec] += 1
        if c.get("created_at"):
            per_day[str(c["created_at"])[:10]] += 1

        action = (state.get("review") or {}).get("action")
        if action in REVIEW_ACTIONS:
            review_totals[action] += 1
            review_by_rec[rec][action] += 1

        case_total = 0
        for e in c.get("events") or []:
            node = e.get("node")
            if node in TIMED_NODES and e.get("latency_ms"):
                latencies[node].append(e["latency_ms"])
                case_total += e["latency_ms"]
            if node in TIMED_NODES:
                tokens_in[node] += e.get("input_tokens") or 0
                tokens_out[node] += e.get("output_tokens") or 0
            if node == "intake" and ((e.get("detail") or {}).get("unverified_quotes") or 0) > 0:
                intake_unverified_cases += 1
        if case_total:
            end_to_end.append(case_total)

        notes = ((state.get("assessment") or {}).get("guardrail_notes")) or []
        if notes:
            guard_cases += 1
            for kind in {guardrail_kind(n) for n in notes}:
                guard_kinds[kind] += 1

        ehr = state.get("ehr")
        if ehr:
            ehr_status[ehr.get("status", "unknown")] += 1
            if ehr.get("status") == "ok":
                ehr_facts.append(len(ehr.get("facts") or []))

        d = state.get("dispatch")
        if d:
            dispatch_status[d.get("status", "unknown")] += 1
            if d.get("status") == "blocked":
                blocked[dispatch_block_reason(d.get("reason", ""))] += 1

    decided = sum(review_totals.values())
    changed = review_totals["edit"] + review_totals["reject"]
    latency = {}
    for node in TIMED_NODES:
        values = latencies.get(node, [])
        if values:
            latency[node] = {
                "count": len(values),
                "p50_ms": percentile(values, 50),
                "p95_ms": percentile(values, 95),
                "mean_ms": round(sum(values) / len(values)),
                "input_tokens": tokens_in[node],
                "output_tokens": tokens_out[node],
            }

    return {
        "total_cases": len(cases),
        "outcomes": {"by_status": dict(by_status), "by_recommendation": dict(by_rec)},
        "review": {
            "decided": decided,
            "approve": review_totals["approve"],
            "edit": review_totals["edit"],
            "reject": review_totals["reject"],
            "change_rate": _rate(changed, decided),
            "by_recommendation": {r: {a: v[a] for a in REVIEW_ACTIONS} for r, v in review_by_rec.items()},
        },
        "latency": latency,
        "end_to_end": {"count": len(end_to_end), "p50_ms": percentile(end_to_end, 50),
                       "p95_ms": percentile(end_to_end, 95)},
        "tokens": {"input": sum(tokens_in.values()), "output": sum(tokens_out.values())},
        "guardrails": {
            "cases_with_any": guard_cases,
            "rate": _rate(guard_cases, len(cases)),
            "by_kind": dict(guard_kinds.most_common()),
            "intake_unverified_quote_cases": intake_unverified_cases,
        },
        "ehr": {
            "by_status": dict(ehr_status),
            "avg_facts": round(sum(ehr_facts) / len(ehr_facts), 1) if ehr_facts else None,
        },
        "dispatch": {"by_status": dict(dispatch_status), "blocked_reasons": dict(blocked)},
        "per_day": [{"date": d, "cases": n} for d, n in sorted(per_day.items())],
    }
