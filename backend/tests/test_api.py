"""Week 5: the API the reviewer UI talks to. No network, no database; the workflow runs on the fake model."""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import main
from test_workflow import DRAFT, NOTE, FakeLLM, _graph

PLACEHOLDER_DRAFT = {"subject": "Prior authorization request", "body": "We request MRI.\n\nSincerely,\n[Ordering provider name]"}


@pytest.fixture
def api(monkeypatch):
    """A client whose workflow is the real graph on the fake model, with nothing written anywhere."""
    state = {"llm": FakeLLM(), "persisted": []}
    graph_holder = {}

    def workflow():
        if "graph" not in graph_holder:
            graph_holder["graph"] = _graph(state["llm"])
        return graph_holder["graph"]

    monkeypatch.setattr(main, "_workflow", workflow)
    monkeypatch.setattr(main, "_persist", lambda view: state["persisted"].append(view["case_id"]))
    monkeypatch.setattr(main, "_saved_state", lambda case_id: None)
    monkeypatch.setattr(main.settings, "api_key", "")
    main._running.clear()

    def use(llm):
        state["llm"] = llm
        graph_holder.clear()

    client = TestClient(main.app)
    client.use_llm, client.persisted = use, state["persisted"]
    return client


def _start(api, **extra):
    r = api.post("/cases", json={"text": NOTE, "source_name": "note.txt", **extra})
    assert r.status_code == 202
    return r.json()["case_id"]


# ------------------------------------------------------------------ starting and reading a case

def test_starting_a_case_returns_its_id_at_once_and_the_case_pauses_for_review(api):
    case_id = _start(api, request_date="2026-03-20")
    view = api.get(f"/cases/{case_id}").json()
    assert view["status"] == "awaiting_review" and view["resumable"] is True
    assert view["recommendation"] == "likely_meets"
    assert view["packet"]["draft"]["kind"] == "submission_letter"
    assert view["note_text"] == NOTE and view["request_date"] == "2026-03-20" and view["source_name"] == "note.txt"
    assert "state" not in view, "the full internal state is not sent to the browser"
    assert api.persisted == [case_id]


def test_wait_true_returns_the_finished_packet(api):
    r = api.post("/cases?wait=true", json={"text": NOTE})
    assert r.json()["status"] == "awaiting_review" and r.json()["packet"]["recommendation"] == "likely_meets"


def test_a_bad_request_date_is_rejected(api):
    assert api.post("/cases", json={"text": NOTE, "request_date": "next tuesday"}).status_code == 422
    assert api.post("/cases", json={"text": "too short"}).status_code == 422


def test_unknown_case_is_404(api):
    assert api.get("/cases/nope").status_code == 404


def test_a_run_that_fails_is_reported_as_failed_not_lost(api, monkeypatch):
    def boom():
        raise RuntimeError("model unavailable")

    calls = {"n": 0}

    def workflow():
        calls["n"] += 1
        if calls["n"] == 1:  # the fail-fast check at request time passes; the background run fails
            return object()
        boom()

    monkeypatch.setattr(main, "_workflow", workflow)
    case_id = api.post("/cases", json={"text": NOTE}).json()["case_id"]
    view = api.get(f"/cases/{case_id}").json()
    assert view["status"] == "failed" and "model unavailable" in view["error"]


def test_a_saved_case_is_shown_read_only_when_the_live_workflow_forgot_it(api, monkeypatch):
    saved = {"case_id": "abc", "note_text": NOTE, "request_date": "2026-03-20", "trace": [],
             "intake": {"result": {"requested_procedure": "MRI"}}, "assessment": None, "draft": None}
    monkeypatch.setattr(main, "_saved_state", lambda case_id: saved if case_id == "abc" else None)
    view = api.get("/cases/abc").json()
    assert view["status"] == "awaiting_review" and view["resumable"] is False


# ------------------------------------------------------------------ the human decision

def test_approve_finalizes_and_a_second_review_is_a_conflict(api):
    case_id = _start(api)
    r = api.post(f"/cases/{case_id}/review", json={"action": "approve", "reviewer": "Nurse Rao"})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    again = api.post(f"/cases/{case_id}/review", json={"action": "approve", "reviewer": "Nurse Rao"})
    assert again.status_code == 409


def test_a_draft_with_placeholders_cannot_be_approved_but_can_be_edited_and_sent(api):
    api.use_llm(FakeLLM(record_draft=PLACEHOLDER_DRAFT))
    case_id = _start(api)
    blocked = api.post(f"/cases/{case_id}/review", json={"action": "approve", "reviewer": "Nurse Rao"})
    assert blocked.status_code == 422 and "[Ordering provider name]" in blocked.json()["detail"]
    assert api.get(f"/cases/{case_id}").json()["status"] == "awaiting_review", "the case stays open for a fix"

    still_blank = api.post(f"/cases/{case_id}/review",
                           json={"action": "edit", "reviewer": "Nurse Rao", "edited_letter": "Sincerely,\n[Provider]"})
    assert still_blank.status_code == 422
    fixed = api.post(f"/cases/{case_id}/review",
                     json={"action": "edit", "reviewer": "Nurse Rao", "edited_letter": "Sincerely, Dr. Arjun Rao"})
    assert fixed.status_code == 200 and fixed.json()["status"] == "approved_with_edits"


def test_rejecting_needs_no_clean_document(api):
    api.use_llm(FakeLLM(record_draft=PLACEHOLDER_DRAFT))
    case_id = _start(api)
    r = api.post(f"/cases/{case_id}/review", json={"action": "reject", "reviewer": "Nurse Rao", "notes": "wrong policy"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"


def test_review_needs_a_reviewer_name_and_an_edit_needs_text(api):
    case_id = _start(api)
    assert api.post(f"/cases/{case_id}/review", json={"action": "approve", "reviewer": "  "}).status_code == 422
    assert api.post(f"/cases/{case_id}/review", json={"action": "edit", "reviewer": "A"}).status_code == 422


def test_reviewing_a_case_the_workflow_never_saw_is_404(api):
    r = api.post("/cases/unknown/review", json={"action": "approve", "reviewer": "Nurse Rao"})
    assert r.status_code == 404 and "CHECKPOINTER=postgres" in r.json()["detail"]


# ------------------------------------------------------------------ the shared secret

def test_when_an_api_key_is_set_every_route_but_health_needs_it(api, monkeypatch):
    monkeypatch.setattr(main.settings, "api_key", "s3cret")
    assert api.get("/health").status_code == 200
    for method, path in (("get", "/cases"), ("get", "/metrics"), ("get", "/samples"), ("post", "/cases")):
        assert getattr(api, method)(path).status_code == 401, path
    assert api.get("/samples", headers={"X-API-Key": "wrong"}).status_code == 401
    assert api.get("/samples", headers={"X-API-Key": "s3cret"}).status_code == 200


# ------------------------------------------------------------------ helpers for the UI

def test_samples_carry_the_note_and_its_visit_date(api):
    samples = api.get("/samples").json()["samples"]
    assert len(samples) >= 6 and all(s["text"] and s["name"].endswith(".txt") for s in samples)
    note_02 = next(s for s in samples if s["name"].startswith("note_02"))
    assert note_02["suggested_request_date"] == "2026-04-02"


def test_metrics_endpoint_returns_the_computed_aggregates(api, monkeypatch):
    monkeypatch.setattr(main.settings, "database_url", "postgresql://test")
    monkeypatch.setattr(main, "_metrics_cases", lambda days: [
        {"case_id": "a", "created_at": "2026-03-01", "status": "approved", "recommendation": "likely_meets",
         "state": {"review": {"action": "approve"}}, "events": [{"node": "assess", "latency_ms": 1000}]}])
    body = api.get("/metrics?days=7").json()
    assert body["days"] == 7 and body["total_cases"] == 1 and body["review"]["approve"] == 1
    assert api.get("/metrics?days=0").status_code == 422


def test_metrics_without_a_database_is_503(api, monkeypatch):
    monkeypatch.setattr(main.settings, "database_url", "")
    assert api.get("/metrics").status_code == 503
