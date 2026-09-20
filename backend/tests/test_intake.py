"""Tests run with a fake Claude client: no network, no API key needed."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.agents.intake import run_intake
from app.main import app
from app.schemas import IntakeResult

NOTE = (
    "Patient SYN-00417. Completed 8 weeks of physical therapy (twice weekly) with minimal improvement.\n"
    "Has tried some\nibuprofen. Positive straight leg raise on the left.\n"
    "No history of cancer. Request MRI lumbar spine."
)


def _fake_client(payload: dict):
    block = SimpleNamespace(type="tool_use", input=payload)
    message = SimpleNamespace(
        content=[block], usage=SimpleNamespace(input_tokens=120, output_tokens=80)
    )
    messages = SimpleNamespace(create=lambda **kwargs: message)
    return SimpleNamespace(messages=messages)


GOOD = {
    "patient_ref": "SYN-00417",
    "age": 54,
    "sex": "Male",
    "requested_procedure": "MRI lumbar spine without contrast",
    "procedure_code": "72148",
    "diagnoses": ["Lumbar radiculopathy"],
    "diagnosis_codes": ["M54.16"],
    "prior_treatments": [
        {
            "finding": "8 weeks physical therapy",
            "source_quote": "Completed 8 weeks of physical therapy (twice weekly) with minimal improvement",
        }
    ],
    "supporting_evidence": [
        {"finding": "Positive straight leg raise", "source_quote": "Positive straight leg raise on the left"}
    ],
    "pertinent_negatives": [
        {"finding": "No history of cancer", "source_quote": "No history of cancer"}
    ],
    "missing_information": [],
    "confidence": 0.92,
}


def test_complete_note_does_not_need_review():
    resp = run_intake(NOTE, client=_fake_client(GOOD), model="test-model")
    assert resp.result.procedure_code == "72148"
    assert resp.needs_human_review is False
    assert resp.unverified_quotes == []
    assert resp.input_tokens == 120


def test_missing_info_forces_human_review():
    payload = {**GOOD, "missing_information": ["Duration of conservative therapy"]}
    resp = run_intake(NOTE, client=_fake_client(payload), model="test-model")
    assert resp.needs_human_review is True


def test_low_confidence_forces_human_review():
    payload = {**GOOD, "confidence": 0.4}
    resp = run_intake(NOTE, client=_fake_client(payload), model="test-model")
    assert resp.needs_human_review is True


def test_fabricated_quote_is_flagged_and_forces_review():
    payload = {
        **GOOD,
        "supporting_evidence": [
            {"finding": "Weight loss", "source_quote": "Patient lost 10 kg over three months"}
        ],
    }
    resp = run_intake(NOTE, client=_fake_client(payload), model="test-model")
    assert resp.unverified_quotes == ["Patient lost 10 kg over three months"]
    assert resp.needs_human_review is True


def test_quote_spanning_a_line_break_is_accepted():
    payload = {
        **GOOD,
        "prior_treatments": [
            {"finding": "Tried ibuprofen", "source_quote": "Has tried some ibuprofen"}
        ],
    }
    resp = run_intake(NOTE, client=_fake_client(payload), model="test-model")
    assert resp.unverified_quotes == []
    assert resp.needs_human_review is False


def test_empty_string_fields_become_none():
    result = IntakeResult.model_validate({**GOOD, "procedure_code": "", "sex": "  "})
    assert result.procedure_code is None
    assert result.sex is None


def test_no_tool_call_raises():
    message = SimpleNamespace(
        content=[SimpleNamespace(type="text")], usage=SimpleNamespace(input_tokens=1, output_tokens=1)
    )
    client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: message))
    with pytest.raises(ValueError):
        run_intake(NOTE, client=client, model="test-model")


def test_health_endpoint():
    assert TestClient(app).get("/health").json()["status"] == "ok"


def test_intake_without_api_key_returns_503(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "anthropic_api_key", "")
    r = TestClient(app).post("/intake", json={"text": "x" * 50})
    assert r.status_code == 503