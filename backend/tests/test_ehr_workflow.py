"""Week 4: the EHR agent, EHR-aware criteria guardrails, and gated outbound dispatch. No network, no subprocess."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.agents import criteria, ehr
from app.fhir.facts import Fact
from app.fhir.source import BundleFhirSource
from app.fhir.tools import FhirTools, tool_specs
from app.mcp_client import InProcessToolbox
from app.schemas import IntakeResult
from app.workflow import dispatch
from app.workflow.graph import Deps, resume_case, start_case
from test_workflow import DRAFT, NOTE, FakeLLM, _criteria, _intake, _policy_chunks, _req

FHIR_DIR = Path(__file__).resolve().parents[1] / "app" / "data" / "fhir"
APPROVE = {"action": "approve", "reviewer": "Nurse Rao"}
REPEAT_MRI = "MRI right knee without contrast [CPT 73721]"


def _fhir_toolbox():
    return InProcessToolbox("fhir", tool_specs(), FhirTools(BundleFhirSource(FHIR_DIR)).call)


class RecordingToolbox(InProcessToolbox):
    def __init__(self, fail=False):
        super().__init__("outbound", [], self._handle)
        self.calls, self.fail = [], fail

    def _handle(self, tool, args):
        if self.fail:
            raise RuntimeError("payer portal down")
        self.calls.append((tool, args))
        return {"status": "submitted" if tool.startswith("submit") else "sent", "reference": "REF-1"}


class ChartLLM(FakeLLM):
    """FakeLLM that also plays the EHR agent: forced tool calls get canned payloads, the free-running
    tool-use loop follows a script of (tool, args) steps."""

    def __init__(self, script, **payloads):
        super().__init__(**payloads)
        self.script, self.rounds, self.seen_tools = list(script), 0, None

    def create(self, **kwargs):
        if "tool_choice" in kwargs:
            return super().create(**kwargs)
        self.rounds += 1
        self.seen_tools = [t["name"] for t in kwargs["tools"]]
        step = self.script.pop(0) if self.script else []
        content = [SimpleNamespace(type="tool_use", id=f"tu{self.rounds}-{i}", name=n, input=a)
                   for i, (n, a) in enumerate(step)]
        content = content or [SimpleNamespace(type="text", text="Looked at therapy, imaging and prior scans.")]
        return SimpleNamespace(content=content, usage=SimpleNamespace(input_tokens=200, output_tokens=40))


def _intake_result(**over) -> IntakeResult:
    return IntakeResult.model_validate(_intake(**over))


POLICY = criteria.format_policy_context(_policy_chunks())


# ------------------------------------------------------------------ the EHR agent loop

def test_agent_collects_facts_returned_by_tools_and_ignores_what_the_model_says():
    llm = ChartLLM([[("get_procedures", {"patient": "SYN-00982"}), ("get_imaging_reports", {"patient": "SYN-00982"})]])
    res = ehr.gather(_intake_result(patient_ref="SYN-00982"), POLICY, "2026-04-05", _fhir_toolbox(), client=llm)
    assert res.status == "ok"
    assert {f.ref for f in res.facts} == {"Procedure/proc-1", "DiagnosticReport/dx-1"}
    assert [c["tool"] for c in res.tool_calls] == ["get_procedures", "get_imaging_reports"]
    assert res.input_tokens > 0 and res.agent_note.startswith("Looked at")
    assert llm.seen_tools == [s["name"] for s in tool_specs()]


def test_agent_cannot_open_another_patients_record():
    llm = ChartLLM([[("get_procedures", {"patient": "SYN-04471"})]])  # not the patient on the request
    res = ehr.gather(_intake_result(patient_ref="SYN-00982"), POLICY, "2026-04-05", _fhir_toolbox(), client=llm)
    assert res.tool_calls[0]["patient_forced"] is True
    assert all("pt-00982" in f.text or "SYN-00982" in f.text or f.ref == "Procedure/proc-1" for f in res.facts)
    assert "S. Kulkarni" in res.facts[0].text  # SYN-00982's therapist, not SYN-04471's (R. Menon)


def test_agent_refuses_tools_outside_the_allow_list():
    llm = ChartLLM([[("delete_patient", {"patient": "SYN-00982"})]])
    res = ehr.gather(_intake_result(patient_ref="SYN-00982"), POLICY, "2026-04-05", _fhir_toolbox(), client=llm)
    assert res.tool_calls[0]["error"] == "tool not allowed" and res.facts == [] and res.status == "no_records"


def test_agent_stops_at_the_round_limit():
    script = [[("get_conditions", {"patient": "SYN-00982"})]] * 10
    llm = ChartLLM(script)
    res = ehr.gather(_intake_result(patient_ref="SYN-00982"), POLICY, "2026-04-05", _fhir_toolbox(), client=llm)
    assert llm.rounds == ehr.MAX_ROUNDS and "limit" in res.agent_note


def test_agent_skips_when_the_note_has_no_patient_identifier():
    res = ehr.gather(_intake_result(patient_ref=None), POLICY, "2026-04-05", _fhir_toolbox(), client=ChartLLM([]))
    assert res.status == "skipped"


def test_agent_reports_patient_not_found_and_never_raises():
    llm = ChartLLM([[("get_conditions", {"patient": "SYN-99999"})]])
    res = ehr.gather(_intake_result(patient_ref="SYN-99999"), POLICY, "2026-04-05", _fhir_toolbox(), client=llm)
    assert res.status == "patient_not_found"

    class Broken(InProcessToolbox):
        def list_tools(self):
            raise ConnectionError("MCP server gone")

    res = ehr.gather(_intake_result(patient_ref="SYN-00982"), POLICY, "2026-04-05",
                     Broken("fhir", [], lambda t, a: {}), client=ChartLLM([]))
    assert res.status == "error" and "MCP server gone" in res.detail


# ------------------------------------------------------------------ guardrails on chart evidence

def _fact(ref, text, kind="exam"):
    return Fact(ref=ref, kind=kind, date="2026-03-24", text=text)


def _one_requirement(quote, status="met"):
    a = criteria.CriteriaAssessment.model_validate(_criteria())
    a.pathways[0].requirements = [
        criteria.RequirementCheck.model_validate(_req("Supportive exam finding", status, "3.2", quote))
    ]
    return a


CHUNKS = [{"policy_id": "MP-IMG-002", "section": "3.2"}, {"policy_id": "MP-GEN-001", "section": "2.4"},
          {"policy_id": "MP-GEN-001", "section": "6"}]


def test_a_quote_from_a_chart_fact_verifies_and_is_labelled_with_its_resource():
    facts = [_fact("Observation/obs-2", "Observation/obs-2 (2026-03-24): McMurray test: positive, by Dr. Shah")]
    clean, notes = criteria.validate(_one_requirement("McMurray test: positive"), "thin note", CHUNKS, facts)
    req = clean.pathways[0].requirements[0]
    assert req.status == "met" and req.evidence_sources == ["Observation/obs-2"]
    assert not any("Supportive exam" in n for n in notes)


def test_note_quotes_are_labelled_note_and_preferred():
    facts = [_fact("Observation/obs-2", "Observation/obs-2: McMurray test: positive")]
    clean, _ = criteria.validate(_one_requirement("positive McMurray test"), "Exam: positive McMurray test.", CHUNKS, facts)
    assert clean.pathways[0].requirements[0].evidence_sources == ["note"]


def test_a_quote_stitched_from_two_chart_facts_does_not_verify():
    facts = [_fact("Observation/obs-1", "Observation/obs-1: Medial joint line tenderness: present"),
             _fact("Observation/obs-2", "Observation/obs-2: McMurray test: positive")]
    stitched = "Medial joint line tenderness: present Observation/obs-2: McMurray test: positive"
    clean, notes = criteria.validate(_one_requirement(stitched), "thin note", CHUNKS, facts)
    assert clean.pathways[0].requirements[0].status == "unclear"
    assert any("neither the note nor the EHR facts" in n for n in notes)


def test_chart_facts_are_ignored_for_verification_when_none_were_retrieved():
    clean, _ = criteria.validate(_one_requirement("McMurray test: positive"), "thin note", CHUNKS, None)
    assert clean.pathways[0].requirements[0].status == "unclear"


def test_billing_codes_can_be_satisfied_by_the_charts_order():
    a = criteria.CriteriaAssessment.model_validate(_criteria())
    g = a.general_requirements[0]
    g.requirement, g.evidence = "CPT and ICD-10 codes must be provided", []
    order = _fact("ServiceRequest/sr-1", "ServiceRequest/sr-1 (2026-04-02): MRI right knee without contrast "
                  "[CPT 73721], reason: Pain in right knee [ICD-10 M25.561], by Dr. Rao", kind="order")
    assert criteria.validate(a, "Wants an MRI of the knee.", CHUNKS, [order])[0].general_requirements[0].status == "met"
    assert criteria.validate(a, "Wants an MRI of the knee.", CHUNKS, [])[0].general_requirements[0].status == "unclear"


def test_chart_evidence_reaches_the_draft_with_its_source():
    a = criteria.CriteriaAssessment.model_validate(_criteria())
    a.pathways[0].requirements[1].evidence_sources = ["Observation/obs-2"]
    summary = criteria.summarize_for_draft(criteria.AssessmentResult(assessment=a, recommendation="likely_meets"))
    assert summary["pathways"][0]["requirements"][1]["quote_sources"] == ["Observation/obs-2"]


# ------------------------------------------------------------------ the graph with the chart lookup

def _graph(llm, ehr_tools=None, outbound_tools=None):
    deps = Deps(retrieve_policy=lambda i: ("MP-IMG-002", _policy_chunks()), llm_client=llm, model="test",
                ehr_tools=ehr_tools, outbound_tools=outbound_tools)
    return __import__("app.workflow.graph", fromlist=["build_graph"]).build_graph(deps, MemorySaver())


def _nodes(view):
    return [e["node"] for e in view["trace"]]


def _thin_note_payloads():
    """The Week 3 incomplete-note case: the note alone leaves the exam requirement unclear."""
    thin = _criteria()
    thin["pathways"][0]["requirements"][1] = _req("Supportive exam finding", "unclear", "3.2")
    return thin


def test_chart_facts_flow_through_the_workflow_and_are_shown_to_the_reviewer():
    fixed = _criteria()
    fixed["pathways"][0]["requirements"][1] = _req("Supportive exam finding", "met", "3.2", "McMurray test: positive")
    llm = ChartLLM([[("get_exam_findings", {"patient": "SYN-00982"})]], record_intake=_intake(patient_ref="SYN-00982"),
                   record_criteria=fixed)
    view = start_case(_graph(llm, _fhir_toolbox()), "Wants an MRI of the right knee.")
    assert _nodes(view) == ["intake", "policy", "ehr", "assess", "draft"]
    packet = view["packet"]
    assert packet["ehr"]["status"] == "ok" and len(packet["ehr"]["facts"]) == 5
    exam = packet["pathways"][0]["requirements"][1]
    assert exam["status"] == "met" and exam["sources"] == ["Observation/obs-2"]
    ehr_event = next(e for e in view["trace"] if e["node"] == "ehr")
    assert ehr_event["detail"]["tools"] == ["get_exam_findings"] and ehr_event["input_tokens"] > 0


def test_a_chart_exclusion_such_as_a_repeat_mri_sends_a_met_pathway_to_a_human():
    payload = _criteria(exclusions_triggered=[{
        "policy_id": "MP-IMG-002", "section": "4", "reason": "repeat MRI within 12 months", "basis": "documented",
        "source_quote": REPEAT_MRI}])
    llm = ChartLLM([[("get_imaging_reports", {"patient": "SYN-04471", "contains": "MRI"})]],
                   record_intake=_intake(patient_ref="SYN-04471"), record_criteria=payload)
    view = start_case(_graph(llm, _fhir_toolbox()), NOTE)
    assert view["recommendation"] == "needs_more_info"
    exclusion = view["packet"]["exclusions_triggered"][0]
    assert exclusion["source"] == "DiagnosticReport/dx-1" and exclusion["basis"] == "documented"


def test_the_workflow_carries_on_with_the_note_alone_when_the_chart_lookup_fails():
    class Broken(InProcessToolbox):
        def list_tools(self):
            raise ConnectionError("MCP server gone")

    llm = ChartLLM([], record_intake=_intake(patient_ref="SYN-00982"))
    view = start_case(_graph(llm, Broken("fhir", [], lambda t, a: {})), NOTE)
    assert view["status"] == "awaiting_review" and view["recommendation"] == "likely_meets"
    assert view["packet"]["ehr"]["status"] == "error"


def test_escalated_cases_never_reach_the_chart_lookup():
    llm = ChartLLM([], record_intake=_intake(confidence=0.3))
    view = start_case(_graph(llm, _fhir_toolbox()), NOTE)
    assert "ehr" not in _nodes(view) and llm.rounds == 0


# ------------------------------------------------------------------ dispatch happens only after approval

def _letter_state(**over):
    state = {
        "case_id": "abc123", "review": {"action": "approve", "reviewer": "Nurse Rao"},
        "draft": {"kind": "submission_letter", "subject": "Request", "body": "Letter", "warnings": []},
        "final_document": "Final letter",
        "intake": {"result": {"patient_ref": "SYN-01203", "procedure_code": "73721", "diagnosis_codes": ["M25.561"]}},
    }
    state.update(over)
    return state


def test_a_submission_letter_goes_to_the_payer_with_the_approvers_name():
    step = dispatch.plan(_letter_state())
    assert step["tool"] == "submit_prior_authorization"
    assert step["args"] == {"case_id": "abc123", "patient": "SYN-01203", "approved_by": "Nurse Rao",
                            "cpt": "73721", "icd10": ["M25.561"], "letter": "Final letter"}


def test_an_information_request_goes_to_the_clinician_and_a_memo_stays_internal():
    info = dispatch.plan(_letter_state(draft={"kind": "information_request", "subject": "Need more", "body": "b"}))
    assert info["tool"] == "send_clinician_message" and info["args"]["subject"] == "Need more"
    memo = dispatch.plan(_letter_state(draft={"kind": "denial_risk_memo", "subject": "s", "body": "b"}))
    assert memo["action"] == "skip"


def test_nothing_is_sent_for_reject_or_when_there_is_no_draft():
    assert dispatch.plan(_letter_state(review={"action": "reject", "reviewer": "Nurse Rao"}))["action"] == "skip"
    assert dispatch.plan(_letter_state(draft=None, final_document="typed by hand"))["action"] == "skip"


def test_submission_codes_fall_back_to_the_charts_order_and_block_when_absent():
    bare = {"result": {"patient_ref": "SYN-00982", "procedure_code": None, "diagnosis_codes": []}}
    assert dispatch.plan(_letter_state(intake=bare))["action"] == "blocked"
    order = {"kind": "order", "ref": "ServiceRequest/sr-1", "text": "ServiceRequest/sr-1 (2026-04-02): MRI right knee "
             "without contrast [CPT 73721], reason: Pain in right knee [ICD-10 M25.561], by Dr. Rao, status active"}
    step = dispatch.plan(_letter_state(intake=bare, ehr={"facts": [order]}))
    assert step["args"]["cpt"] == "73721" and step["args"]["icd10"] == ["M25.561"]


def test_approve_triggers_exactly_one_outbound_call_and_reject_triggers_none():
    outbound = RecordingToolbox()
    graph = _graph(FakeLLM(), outbound_tools=outbound)
    view = start_case(graph, NOTE)
    assert outbound.calls == []  # a paused case sends nothing
    done = resume_case(graph, view["case_id"], APPROVE)
    assert done["dispatch"] == {"status": "submitted", "tool": "submit_prior_authorization", "reference": "REF-1"}
    assert [c[0] for c in outbound.calls] == ["submit_prior_authorization"]
    assert outbound.calls[0][1]["approved_by"] == "Nurse Rao" and outbound.calls[0][1]["cpt"] == "73721"
    assert _nodes(done)[-3:] == ["human_review", "finalize", "dispatch"]

    other = RecordingToolbox()
    graph = _graph(FakeLLM(), outbound_tools=other)
    view = start_case(graph, NOTE)
    done = resume_case(graph, view["case_id"], {**APPROVE, "action": "reject"})
    assert other.calls == [] and done["dispatch"]["status"] == "skipped"


def test_a_failed_send_is_recorded_but_does_not_undo_the_reviewers_decision():
    graph = _graph(FakeLLM(), outbound_tools=RecordingToolbox(fail=True))
    view = start_case(graph, NOTE)
    done = resume_case(graph, view["case_id"], APPROVE)
    assert done["status"] == "approved" and done["dispatch"]["status"] == "failed"
    assert "payer portal down" in done["dispatch"]["error"]


def test_a_document_with_unfilled_placeholders_is_never_sent():
    for kind, extra in (("submission_letter", {}), ("information_request", {"draft": {"kind": "information_request", "subject": "s", "body": "b"}})):
        step = dispatch.plan(_letter_state(final_document="Sincerely,\n[Ordering provider name]", **extra))
        assert step["action"] == "blocked" and "[Ordering provider name]" in step["reason"], kind


def test_a_filled_in_document_is_sent_and_ordinary_brackets_do_not_block():
    step = dispatch.plan(_letter_state(final_document="Sincerely,\nDr. Arjun Rao. See note [1] for dates."))
    assert step["action"] == "call"
