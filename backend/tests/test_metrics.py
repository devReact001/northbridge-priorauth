"""Week 5: the numbers behind the observability dashboard. Pure functions, no database."""

from app.workflow import metrics


def _case(cid, rec="likely_meets", status="approved", action="approve", notes=(), ehr=None, dispatch=None,
          events=None, created="2026-03-01T10:00:00", unverified=0):
    events = events if events is not None else [
        {"node": "intake", "latency_ms": 5000, "input_tokens": 1000, "output_tokens": 300, "detail": {"unverified_quotes": unverified}},
        {"node": "assess", "latency_ms": 40000, "input_tokens": 5000, "output_tokens": 3000, "detail": {}},
        {"node": "human_review", "latency_ms": 0, "input_tokens": 0, "output_tokens": 0, "detail": {}},
    ]
    state = {"review": {"action": action} if action else None,
             "assessment": {"guardrail_notes": list(notes)}}
    if ehr:
        state["ehr"] = ehr
    if dispatch:
        state["dispatch"] = dispatch
    return {"case_id": cid, "created_at": created, "status": status, "recommendation": rec, "state": state, "events": events}


def test_percentile_is_nearest_rank_and_none_when_empty():
    assert metrics.percentile([], 50) is None
    assert metrics.percentile([10], 95) == 10
    values = list(range(1, 101))
    assert metrics.percentile(values, 50) == 50 and metrics.percentile(values, 95) == 95
    assert metrics.percentile([3, 1, 2], 50) == 2


def test_guardrail_notes_are_bucketed_by_what_fired():
    cases = {
        "dropped a quote that appears in neither the note nor the EHR facts: 'x'": "quote_not_in_source",
        "general / CPT: the required code is present in the note or chart, upgraded to met": "code_check_upgrade",
        "MP-IMG-002 3.1: a prerequisite is not an approval pathway, its requirements were moved": "prerequisite_as_pathway",
        "the model was cut off at the token limit at first; asked again and it did": "truncated_retry",
        "the model returned no pathways at first; asked again and it did": "empty_pathways_retry",
        "the model returned no pathways twice; the recommendation is a default": "empty_pathways_default",
        "exclusion MP-IMG-002 4: wording is about absence, treated as missing documentation": "absence_exclusion",
        "something new the code says": "other",
    }
    for note, kind in cases.items():
        assert metrics.guardrail_kind(note) == kind, note


def test_outcomes_and_reviewer_behaviour():
    out = metrics.compute([
        _case("a", "likely_meets", "approved", "approve"),
        _case("b", "likely_meets", "approved_with_edits", "edit"),
        _case("c", "needs_more_info", "rejected", "reject"),
        _case("d", "needs_more_info", "awaiting_review", None),
    ])
    assert out["total_cases"] == 4
    assert out["outcomes"]["by_recommendation"] == {"likely_meets": 2, "needs_more_info": 2}
    assert out["outcomes"]["by_status"]["awaiting_review"] == 1
    r = out["review"]
    assert (r["decided"], r["approve"], r["edit"], r["reject"]) == (3, 1, 1, 1)
    assert r["change_rate"] == 0.667, "edits and rejections are the reviewer changing the machine's answer"
    assert r["by_recommendation"]["likely_meets"] == {"approve": 1, "edit": 1, "reject": 0}


def test_latency_is_per_step_and_ignores_time_spent_waiting_for_a_person():
    out = metrics.compute([_case("a"), _case("b", events=[
        {"node": "intake", "latency_ms": 7000, "input_tokens": 1000, "output_tokens": 200, "detail": {}},
        {"node": "assess", "latency_ms": 60000, "input_tokens": 5000, "output_tokens": 4000, "detail": {}},
        {"node": "human_review", "latency_ms": 999999, "input_tokens": 0, "output_tokens": 0, "detail": {}},
    ])])
    assert set(out["latency"]) == {"intake", "assess"}
    assert out["latency"]["assess"]["p50_ms"] == 40000 and out["latency"]["assess"]["p95_ms"] == 60000
    assert out["latency"]["assess"]["output_tokens"] == 7000
    assert out["end_to_end"] == {"count": 2, "p50_ms": 45000.0, "p95_ms": 67000.0}
    assert out["tokens"] == {"input": 12000, "output": 7500}


def test_guardrail_activity_counts_cases_once_per_kind():
    out = metrics.compute([
        _case("a", notes=["dropped a quote a", "dropped a quote b", "upgraded to met"]),
        _case("b", notes=["dropped a quote c"], unverified=2),
        _case("c"),
    ])
    g = out["guardrails"]
    assert g["cases_with_any"] == 2 and g["rate"] == 0.667
    assert g["by_kind"] == {"quote_not_in_source": 2, "code_check_upgrade": 1}
    assert g["intake_unverified_quote_cases"] == 1


def test_ehr_and_dispatch_health():
    out = metrics.compute([
        _case("a", ehr={"status": "ok", "facts": [1] * 10}, dispatch={"status": "submitted"}),
        _case("b", ehr={"status": "ok", "facts": [1] * 6}, dispatch={"status": "blocked", "reason": "The document still has placeholders to fill in: [Date]. Edit it"}),
        _case("c", ehr={"status": "error", "facts": []}, dispatch={"status": "failed", "error": "down"}),
        _case("d", ehr={"status": "no_records", "facts": []}, dispatch={"status": "skipped", "reason": "x"}),
    ])
    assert out["ehr"] == {"by_status": {"ok": 2, "error": 1, "no_records": 1}, "avg_facts": 8.0}
    assert out["dispatch"]["by_status"] == {"submitted": 1, "blocked": 1, "failed": 1, "skipped": 1}
    assert out["dispatch"]["blocked_reasons"] == {"placeholders_left": 1}


def test_volume_per_day_and_an_empty_database():
    out = metrics.compute([_case("a", created="2026-03-01T09:00"), _case("b", created="2026-03-01T15:00"),
                           _case("c", created="2026-03-02T09:00")])
    assert out["per_day"] == [{"date": "2026-03-01", "cases": 2}, {"date": "2026-03-02", "cases": 1}]
    empty = metrics.compute([])
    assert empty["total_cases"] == 0 and empty["review"]["change_rate"] is None and empty["latency"] == {}
    assert empty["end_to_end"]["p50_ms"] is None and empty["guardrails"]["rate"] is None
