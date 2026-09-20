"""FHIR data layer: synthetic bundles, fact text, the read-only tool surface, and the HTTP source."""

from pathlib import Path

import httpx
import pytest

from app.fhir.facts import summarize
from app.fhir.source import BundleFhirSource, HttpFhirSource
from app.fhir.tools import MAX_FACTS, TOOLS, FhirTools, tool_specs

FHIR_DIR = Path(__file__).resolve().parents[1] / "app" / "data" / "fhir"
PATIENTS = ["SYN-00417", "SYN-00982", "SYN-01203", "SYN-02218", "SYN-03377", "SYN-04471"]


@pytest.fixture(scope="module")
def tools():
    return FhirTools(BundleFhirSource(FHIR_DIR))


def _texts(result):
    return [f["text"] for f in result["facts"]]


def test_every_sample_patient_resolves_by_identifier_and_by_fhir_id():
    source = BundleFhirSource(FHIR_DIR)
    for syn in PATIENTS:
        patient = source.find_patient(syn)
        assert patient is not None
        assert source.find_patient(patient["id"])["id"] == patient["id"]
        assert source.find_patient(syn.lower())["id"] == patient["id"]
    assert source.find_patient("SYN-99999") is None


def test_patient_facts_leave_out_names_and_addresses(tools):
    text = _texts(tools.call("get_patient", {"patient": "SYN-00982"}))[0]
    assert "identifier SYN-00982" in text and "female" in text
    assert "name" not in text.lower() and "address" not in text.lower()


def test_the_incomplete_note_patient_has_the_chart_evidence_the_note_lacks(tools):
    therapy = _texts(tools.call("get_procedures", {"patient": "SYN-00982"}))[0]
    assert "Physical therapy" in therapy and "2026-02-16 to 2026-03-30" in therapy and "S. Kulkarni" in therapy
    assert "Outcome: Pain with stairs unchanged after 6 weeks of therapy." in therapy
    xray = _texts(tools.call("get_imaging_reports", {"patient": "SYN-00982"}))
    assert len(xray) == 1 and "CPT 73560" in xray[0] and "No fracture" in xray[0]
    order = _texts(tools.call("get_service_requests", {"patient": "SYN-00982"}))[0]
    assert "CPT 73721" in order and "ICD-10 M25.561" in order
    findings = " ".join(_texts(tools.call("get_exam_findings", {"patient": "SYN-00982"})))
    assert "McMurray test: positive" in findings
    # the one real gap: locking or catching is recorded nowhere in the chart
    everything = " ".join(t for name in TOOLS for t in _texts(tools.call(name, {"patient": "SYN-00982"})))
    assert "locking" not in everything.lower() and "catching" not in everything.lower()


def test_repeat_mri_is_visible_only_in_the_chart_of_the_repeat_patient(tools):
    prior = [t for t in _texts(tools.call("get_imaging_reports", {"patient": "SYN-04471"})) if "MRI" in t]
    assert len(prior) == 1 and prior[0].startswith("DiagnosticReport/dx-1 (2026-01-14)")
    assert [t for t in _texts(tools.call("get_imaging_reports", {"patient": "SYN-01203"})) if "MRI" in t] == []


def test_results_come_newest_first(tools):
    result = tools.call("get_imaging_reports", {"patient": "SYN-04471"})
    assert [f["date"] for f in result["facts"]] == ["2026-03-02", "2026-01-14"]


def test_an_agent_cannot_hide_evidence_from_itself_with_filters(tools):
    """Regression: a keyword filter once dropped the therapy and exam facts. Extra arguments are now ignored."""
    plain = tools.call("get_procedures", {"patient": "SYN-00982"})
    filtered = tools.call("get_procedures", {"patient": "SYN-00982", "contains": "knee", "since": "2026-04-01"})
    assert filtered["facts"] == plain["facts"] and plain["count"] == 1
    exam = tools.call("get_exam_findings", {"patient": "SYN-00982", "contains": "knee"})
    assert exam["count"] == 5


def test_error_results_are_data_not_exceptions(tools):
    assert tools.call("get_conditions", {"patient": "SYN-99999"})["error"] == "patient_not_found"
    assert tools.call("get_conditions", {"patient": ""})["error"] == "patient is required"
    assert "unknown tool" in tools.call("delete_everything", {"patient": "SYN-00982"})["error"]


def test_tool_surface_is_read_only_and_has_no_free_form_query():
    names = {s["name"] for s in tool_specs()}
    assert names == set(TOOLS)
    assert not any(word in n for n in names for word in ("create", "update", "delete", "write", "search", "query"))
    for spec in tool_specs():
        assert spec["input_schema"]["required"] == ["patient"]


def test_results_are_capped():
    class Many:
        def find_patient(self, ref):
            return {"resourceType": "Patient", "id": "p"}

        def search(self, resource_type, patient_id, category=None):
            return [{"resourceType": "Condition", "id": f"c{i}", "code": {"text": f"Dx {i}"},
                     "onsetDateTime": f"2026-01-{i % 28 + 1:02d}"} for i in range(MAX_FACTS + 15)]

    result = FhirTools(Many()).call("get_conditions", {"patient": "p"})
    assert result["count"] == MAX_FACTS + 15 and len(result["facts"]) == MAX_FACTS and result["truncated"]


def test_summaries_survive_missing_fields():
    assert summarize({"resourceType": "Observation", "id": "o"}).text.startswith("Observation/o")
    assert summarize({"resourceType": "Procedure", "id": "p"}).kind == "procedure"
    assert summarize({"resourceType": "AllergyIntolerance", "id": "a"}) is None


def test_http_source_uses_standard_fhir_search_parameters():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, dict(request.url.params)))
        if request.url.path.endswith("/Patient"):
            if request.url.params.get("identifier") == "SYN-00982":
                return httpx.Response(200, json={"entry": [{"resource": {"resourceType": "Patient", "id": "abc"}}]})
            return httpx.Response(200, json={"entry": []})
        if request.url.path.endswith("/Patient/nobody"):
            return httpx.Response(404, json={})
        return httpx.Response(200, json={"entry": [
            {"resource": {"resourceType": "Observation", "id": "o1"}},
            {"resource": {"resourceType": "OperationOutcome", "id": "ignored"}},
        ]})

    client = httpx.Client(base_url="https://fhir.example/r4/", transport=httpx.MockTransport(handler))
    source = HttpFhirSource("https://fhir.example/r4", client=client)
    assert source.find_patient("SYN-00982")["id"] == "abc"
    assert source.find_patient("nobody") is None
    found = source.search("Observation", "abc", category="exam")
    assert [r["id"] for r in found] == ["o1"]
    path, params = seen[-1]
    assert path.endswith("/Observation") and params == {"patient": "abc", "_count": "50", "category": "exam"}
