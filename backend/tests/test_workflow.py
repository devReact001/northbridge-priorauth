"""Workflow tests: fake Claude, real policy PDFs (chunked), in-memory checkpointer. No network, no database."""

import copy
from pathlib import Path
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import MemorySaver

from app.agents import criteria, drafter
from app.agents.criteria import GENERAL_POLICY_ID, GENERAL_SECTIONS
from app.rag.chunking import chunk_directory
from app.workflow.graph import Deps, NotAwaitingReview, build_graph, case_view, resume_case, start_case
from app.workflow.state import ReviewDecision

PDF_DIR = Path(__file__).resolve().parents[2] / "policies" / "pdf"

NOTE = """Patient SYN-01203, 41 year old male. Visit 2026-03-12.
Right knee pain for 8 weeks after a twisting injury. Reports locking and catching of the right knee.
Completed 6 weeks of physical therapy twice weekly and naproxen 500 mg twice daily with minimal improvement.
Exam: medial joint line tenderness, positive McMurray test, mild effusion.
Weight-bearing radiographs of the right knee on 2026-02-20 showed no fracture.
Plan: MRI right knee without contrast (CPT 73721). Diagnosis M25.561."""

THERAPY_QUOTE = "Completed 6 weeks of physical therapy twice weekly"


def _intake(**over):
    d = {
        "patient_ref": "SYN-01203", "age": 41, "sex": "Male",
        "requested_procedure": "MRI right knee without contrast", "procedure_code": "73721",
        "diagnoses": ["Right knee pain"], "diagnosis_codes": ["M25.561"],
        "prior_treatments": [{"finding": "6 weeks PT and naproxen", "source_quote": THERAPY_QUOTE}],
        "supporting_evidence": [{"finding": "Positive McMurray", "source_quote": "positive McMurray test"}],
        "pertinent_negatives": [], "missing_information": [], "confidence": 0.9,
    }
    d.update(over)
    return d


def _req(text, status, section, quote=None, policy="MP-IMG-002"):
    ev = [{"finding": text, "source_quote": quote}] if quote else []
    return {"requirement": text, "status": status, "policy_id": policy, "section": section,
            "evidence": ev, "rationale": "because"}


def _criteria(**over):
    d = {
        "policy_applies": True, "applicable_policy_id": "MP-IMG-002",
        "pathways": [{
            "name": "Suspected meniscal tear", "policy_id": "MP-IMG-002", "section": "3.2",
            "requirements": [
                _req("Mechanical symptoms", "met", "3.2", "Reports locking and catching of the right knee"),
                _req("Supportive exam finding", "met", "3.2", "positive McMurray test"),
                _req("4 weeks of conservative therapy", "met", "3.2", THERAPY_QUOTE),
            ],
        }],
        "exclusions_triggered": [],
        "general_requirements": [
            _req("Laterality stated", "met", "2.4", "Right knee pain for 8 weeks", policy=GENERAL_POLICY_ID),
            _req("Therapy documented by a clinician", "met", "6", THERAPY_QUOTE, policy=GENERAL_POLICY_ID),
        ],
        "summary": "The note supports the meniscal tear pathway.",
    }
    d.update(over)
    return d


DRAFT = {
    "subject": "Prior authorization request: MRI right knee",
    "body": "We request MRI right knee without contrast (CPT 73721, M25.561). Criteria met (MP-IMG-002 section 3.2).",
}


class FakeLLM:
    """Stands in for the Anthropic client. Returns a canned payload per tool name."""

    def __init__(self, **payloads):
        self.payloads = {"record_intake": _intake(), "record_criteria": _criteria(), "record_draft": dict(DRAFT)}
        self.payloads.update(payloads)
        self.calls: list[str] = []
        self.messages = self

    def create(self, **kwargs):
        name = kwargs["tools"][0]["name"]
        self.calls.append(name)
        block = SimpleNamespace(type="tool_use", input=copy.deepcopy(self.payloads[name]))
        return SimpleNamespace(content=[block], usage=SimpleNamespace(input_tokens=100, output_tokens=50))


def _policy_chunks(policy_id="MP-IMG-002"):
    chunks = chunk_directory(PDF_DIR)
    picked = [c for c in chunks if c.policy_id == policy_id]
    picked += [c for c in chunks if c.policy_id == GENERAL_POLICY_ID and c.section in GENERAL_SECTIONS]
    return [{"id": i, "policy_id": c.policy_id, "section": c.section, "heading": c.heading,
             "page": c.page, "content": c.text, "score": 1.0} for i, c in enumerate(picked)]


def _graph(llm, retrieve=None):
    retrieve = retrieve or (lambda intake: ("MP-IMG-002", _policy_chunks()))
    return build_graph(Deps(retrieve_policy=retrieve, llm_client=llm, model="test"), MemorySaver())


def _nodes(view):
    return [e["node"] for e in view["trace"]]


APPROVE = {"action": "approve", "reviewer": "Nurse Rao"}


# ---------------------------------------------------------------- happy path and human review

def test_case_pauses_for_review_and_is_not_auto_approved():
    graph = _graph(FakeLLM())
    view = start_case(graph, NOTE)
    assert view["status"] == "awaiting_review"
    assert view["recommendation"] == "likely_meets"
    assert view["final_document"] is None
    assert view["packet"]["draft"]["kind"] == "submission_letter"
    assert view["packet"]["allowed_actions"] == ["approve", "edit", "reject"]
    assert _nodes(view) == ["intake", "policy", "assess", "draft"]
    assert "finalize" not in _nodes(view)


def test_approve_finalizes_with_the_draft():
    graph = _graph(FakeLLM())
    view = start_case(graph, NOTE)
    done = resume_case(graph, view["case_id"], APPROVE)
    assert done["status"] == "approved"
    assert done["final_document"] == DRAFT["body"]
    assert _nodes(done)[-2:] == ["human_review", "finalize"]


def test_edit_uses_the_reviewers_text():
    graph = _graph(FakeLLM())
    view = start_case(graph, NOTE)
    done = resume_case(graph, view["case_id"], {**APPROVE, "action": "edit", "edited_letter": "Reviewer wording."})
    assert done["status"] == "approved_with_edits"
    assert done["final_document"] == "Reviewer wording."


def test_reject_produces_no_document():
    graph = _graph(FakeLLM())
    view = start_case(graph, NOTE)
    done = resume_case(graph, view["case_id"], {**APPROVE, "action": "reject", "notes": "Wrong patient"})
    assert done["status"] == "rejected" and done["final_document"] is None
    assert done["review"]["notes"] == "Wrong patient"


def test_a_finished_case_cannot_be_reviewed_again():
    graph = _graph(FakeLLM())
    view = start_case(graph, NOTE)
    resume_case(graph, view["case_id"], APPROVE)
    with pytest.raises(NotAwaitingReview):
        resume_case(graph, view["case_id"], APPROVE)


def test_unknown_case_id_raises_key_error():
    with pytest.raises(KeyError):
        resume_case(_graph(FakeLLM()), "nope", APPROVE)


def test_trace_records_tokens_for_llm_steps():
    view = start_case(_graph(FakeLLM()), NOTE)
    by_node = {e["node"]: e for e in view["trace"]}
    assert by_node["assess"]["input_tokens"] == 100 and by_node["draft"]["output_tokens"] == 50
    assert by_node["policy"]["detail"]["policy_id"] == "MP-IMG-002"


# ---------------------------------------------------------------- routing

def test_unclear_requirement_routes_to_information_request():
    weak = _criteria()
    weak["pathways"][0]["requirements"][2] = _req("4 weeks of conservative therapy", "unclear", "3.2")
    view = start_case(_graph(FakeLLM(record_criteria=weak)), NOTE)
    assert view["recommendation"] == "needs_more_info"
    assert view["packet"]["draft"]["kind"] == "information_request"


def test_failed_pathway_routes_to_denial_risk_memo():
    failed = _criteria()
    failed["pathways"][0]["requirements"][2] = _req("4 weeks of conservative therapy", "not_met", "3.2", quote=THERAPY_QUOTE)
    view = start_case(_graph(FakeLLM(record_criteria=failed)), NOTE)
    assert view["recommendation"] == "likely_not_meets"
    assert view["packet"]["draft"]["kind"] == "denial_risk_memo"


def test_low_confidence_extraction_escalates_and_skips_the_criteria_agent():
    llm = FakeLLM(record_intake=_intake(confidence=0.3))
    graph = _graph(llm)
    view = start_case(graph, NOTE)
    assert view["status"] == "awaiting_review"
    assert "record_criteria" not in llm.calls and "record_draft" not in llm.calls
    assert _nodes(view) == ["intake", "escalate"]
    assert view["packet"]["allowed_actions"] == ["edit", "reject"]
    assert "confidence" in view["packet"]["escalation_reason"].lower()
    with pytest.raises(ValueError):  # nothing to approve on an escalated case
        resume_case(graph, view["case_id"], APPROVE)


def test_no_matching_policy_escalates():
    graph = _graph(FakeLLM(), retrieve=lambda intake: (None, []))
    view = start_case(graph, NOTE)
    assert _nodes(view) == ["intake", "policy", "escalate"]
    assert "No payer policy" in view["packet"]["escalation_reason"]


def test_policy_that_does_not_cover_the_procedure_escalates():
    llm = FakeLLM(record_criteria=_criteria(policy_applies=False, pathways=[], general_requirements=[]))
    view = start_case(_graph(llm), NOTE)
    assert view["recommendation"] == "no_applicable_policy"
    assert _nodes(view) == ["intake", "policy", "assess", "escalate"]
    assert "record_draft" not in llm.calls


# ---------------------------------------------------------------- guardrails

def test_fabricated_quote_downgrades_met_to_unclear():
    bad = _criteria()
    bad["pathways"][0]["requirements"][0] = _req("Mechanical symptoms", "met", "3.2", "Knee locks daily and gives way")
    view = start_case(_graph(FakeLLM(record_criteria=bad)), NOTE)
    assert view["recommendation"] == "needs_more_info"
    notes = view["packet"]["guardrail_notes"]
    assert any("appears in neither the note nor the EHR facts" in n for n in notes)
    assert any("downgraded to unclear" in n for n in notes)


def test_citation_outside_the_provided_policy_is_downgraded():
    bad = _criteria()
    bad["pathways"][0]["requirements"][0] = _req(
        "Mechanical symptoms", "met", "9.9", "Reports locking and catching of the right knee"
    )
    view = start_case(_graph(FakeLLM(record_criteria=bad)), NOTE)
    assert view["recommendation"] == "needs_more_info"
    assert any("not in the policy provided" in n for n in view["packet"]["guardrail_notes"])


def test_draft_with_invented_code_is_flagged_for_the_reviewer():
    llm = FakeLLM(record_draft={"subject": "x", "body": "Requesting CPT 99999 and M99.999."})
    view = start_case(_graph(llm), NOTE)
    warnings = view["packet"]["draft"]["warnings"]
    assert any("99999" in w for w in warnings) and any("M99.999" in w for w in warnings)


# ---------------------------------------------------------------- pure decision logic

def _assessment(**over):
    return criteria.CriteriaAssessment.model_validate(_criteria(**over))


def test_decide_all_clear():
    assert criteria.decide(_assessment()) == "likely_meets"


def test_decide_met_pathway_with_exclusion_needs_a_human_to_resolve():
    ex = [{"policy_id": "MP-IMG-002", "section": "4", "reason": "repeat MRI", "basis": "documented", "source_quote": "x"}]
    assert criteria.decide(_assessment(exclusions_triggered=ex)) == "needs_more_info"


def test_decide_exclusion_without_a_met_pathway_is_not_met():
    a = _assessment(exclusions_triggered=[{"policy_id": "MP-IMG-002", "section": "4", "reason": "r", "basis": "documented", "source_quote": "x"}])
    a.pathways[0].requirements[2].status = "not_met"
    assert criteria.decide(a) == "likely_not_meets"


def test_decide_general_requirement_gap_pends_the_request():
    a = _assessment()
    a.general_requirements[0].status = "unclear"
    assert criteria.decide(a) == "needs_more_info"


def test_decide_no_pathways_needs_more_info():
    assert criteria.decide(_assessment(pathways=[])) == "needs_more_info"


def test_check_codes_ignores_codes_present_in_the_source():
    assert drafter.check_codes("CPT 73721 and M25.561", "73721 ... M25.561") == []
    assert len(drafter.check_codes("CPT 12345", "73721")) == 1


# ---------------------------------------------------------------- review payload validation

def test_review_decision_validation():
    with pytest.raises(ValueError):
        ReviewDecision(action="edit", reviewer="Rao")  # edit needs text
    with pytest.raises(ValueError):
        ReviewDecision(action="approve", reviewer="  ")
    assert ReviewDecision(action="approve", reviewer="Rao").notes == ""


def test_case_view_of_unknown_case_is_none():
    assert case_view(_graph(FakeLLM()), "missing") is None


def test_decide_exclusion_that_is_only_missing_documentation_asks_for_information():
    ex = [{"policy_id": "MP-IMG-002", "section": "4", "reason": "no exam documented",
           "basis": "missing_documentation", "source_quote": ""}]
    a = _assessment(exclusions_triggered=ex)
    for r in a.pathways[0].requirements:
        r.status = "unclear"
    assert criteria.decide(a) == "needs_more_info"


def test_not_met_without_a_verified_quote_is_downgraded_to_unclear():
    a = _assessment()
    r = a.pathways[0].requirements[0]
    r.status = "not_met"
    r.evidence = []
    chunks = [{"policy_id": r.policy_id, "section": r.section}]
    clean, notes = criteria.validate(a, "some note text", chunks)
    assert clean.pathways[0].requirements[0].status == "unclear"
    assert any("not_met" in n for n in notes)


def test_documented_exclusion_without_a_verified_quote_is_treated_as_missing_documentation():
    ex = [{"policy_id": "MP-IMG-002", "section": "4", "reason": "no exam", "basis": "documented",
           "source_quote": "text that is not in the note"}]
    a = _assessment(exclusions_triggered=ex)
    chunks = [{"policy_id": "MP-IMG-002", "section": s} for s in ("3.1", "3.2", "3.3", "2.2", "2.3", "2.4", "6")]
    clean, notes = criteria.validate(a, "some note text", chunks)
    assert clean.exclusions_triggered[0].basis == "missing_documentation"
    assert any("missing documentation" in n for n in notes)


def test_documented_exclusion_alone_is_not_enough_when_every_pathway_is_unclear():
    """Incomplete note: the model calls 'exam limited' a documented exclusion, but nothing is affirmatively unmet."""
    ex = [{"policy_id": "MP-IMG-002", "section": "4", "reason": "no exam documented",
           "basis": "documented", "source_quote": "exam limited"}]
    a = _assessment(exclusions_triggered=ex)
    for r in a.pathways[0].requirements:
        r.status = "unclear"
    assert criteria.decide(a) == "needs_more_info"


def test_general_requirement_not_applicable_does_not_block_a_met_pathway():
    a = _assessment()
    a.general_requirements[0].status = "not_applicable"
    assert criteria.decide(a) == "likely_meets"


def test_not_applicable_on_a_pathway_requirement_is_set_to_unclear():
    a = _assessment()
    r = a.pathways[0].requirements[0]
    r.status = "not_applicable"
    chunks = [{"policy_id": r.policy_id, "section": r.section}]
    clean, notes = criteria.validate(a, "some note text", chunks)
    assert clean.pathways[0].requirements[0].status == "unclear"
    assert any("not_applicable" in n for n in notes)


def test_codes_requirement_is_satisfied_by_codes_in_the_note_without_a_quote():
    a = _assessment()
    g = a.general_requirements[0]
    g.requirement, g.evidence = "CPT and ICD-10 codes must be provided", []
    note = "Assessment: Lumbar radiculopathy (M54.16). Plan: MRI lumbar spine (CPT 72148)."
    chunks = [{"policy_id": p.policy_id, "section": p.section} for p in [g] + a.pathways[0].requirements]
    clean, _ = criteria.validate(a, note, chunks)
    assert clean.general_requirements[0].status == "met"
    clean, _ = criteria.validate(a, "Plan: MRI lumbar spine.", chunks)
    assert clean.general_requirements[0].status == "unclear"


def test_draft_input_shows_only_the_met_pathway_when_one_is_met():
    a = _assessment()
    other = a.pathways[0].model_copy(deep=True)
    other.name, other.section = "Other pathway", "3.9"
    other.requirements[0].status = "unclear"
    a.pathways.append(other)
    result = criteria.AssessmentResult(assessment=a, recommendation="needs_more_info")
    names = [p["name"] for p in criteria.summarize_for_draft(result)["pathways"]]
    assert names == ["Suspected meniscal tear"]


def test_decide_a_documentation_gap_exclusion_does_not_block_a_met_pathway():
    ex = [{"policy_id": "MP-IMG-002", "section": "4", "reason": "no exam in note", "basis": "missing_documentation", "source_quote": ""}]
    assert criteria.decide(_assessment(exclusions_triggered=ex)) == "likely_meets"


def test_items_from_a_required_documentation_section_are_not_kept_as_exclusions():
    ex = [
        {"policy_id": "MP-IMG-002", "section": "4", "reason": "no exam", "basis": "missing_documentation", "source_quote": ""},
        {"policy_id": "MP-IMG-002", "section": "5", "reason": "dates not documented", "basis": "missing_documentation", "source_quote": ""},
    ]
    chunks = [{"policy_id": "MP-IMG-002", "section": s, "heading": h} for s, h in
              (("3.1", "Radiograph prerequisite"), ("3.2", "Suspected meniscal tear"), ("3.3", "Suspected ligament injury"),
               ("2.2", "x"), ("2.3", "x"), ("2.4", "x"), ("6", "x"), ("4", "Exclusions"), ("5", "Required documentation"))]
    clean, notes = criteria.validate(_assessment(exclusions_triggered=ex), "some note text", chunks)
    assert [e.section for e in clean.exclusions_triggered] == ["4"]
    assert any("not an exclusions section" in n for n in notes)


def test_an_absence_exclusion_the_model_calls_documented_is_forced_to_missing_documentation():
    ex = [{"policy_id": "MP-IMG-002", "section": "4", "reason": "No physical examination of the knee documented in the clinical note",
           "basis": "documented", "source_quote": "Exam limited today due to time."}]
    chunks = [{"policy_id": "MP-IMG-002", "section": s, "heading": "Exclusions" if s == "4" else "x"} for s in ("3.1", "3.2", "3.3", "2.2", "2.3", "2.4", "6", "4")]
    clean, _ = criteria.validate(_assessment(exclusions_triggered=ex), "Exam limited today due to time.", chunks)
    assert clean.exclusions_triggered[0].basis == "missing_documentation"


def test_one_ruled_out_pathway_with_others_unclear_is_not_a_denial_risk():
    a = _assessment(exclusions_triggered=[{"policy_id": "MP-IMG-002", "section": "4", "reason": "repeat MRI",
                                           "basis": "documented", "source_quote": "x"}])
    a.pathways[0].requirements[0].status = "not_met"
    a.pathways = a.pathways[:1] + [a.pathways[0].model_copy(deep=True)]
    for r in a.pathways[1].requirements:
        r.status = "unclear"
    assert criteria.decide(a) == "needs_more_info"


class _EmptyThenFull(FakeLLM):
    """First criteria answer has no pathways; later ones are the normal payload."""

    def __init__(self, second_empty=False):
        super().__init__()
        self.second_empty = second_empty

    def create(self, **kwargs):
        if kwargs["tools"][0]["name"] == "record_criteria":
            n = self.calls.count("record_criteria")
            if n == 0 or self.second_empty:
                self.payloads["record_criteria"] = _criteria(pathways=[])
            else:
                self.payloads["record_criteria"] = _criteria()
        return super().create(**kwargs)


def _assess_with(llm):
    intake = criteria.IntakeResult.model_validate(_intake())
    return criteria.assess(NOTE, intake, _policy_chunks(), "2026-03-01", client=llm)


def test_a_skipped_pathway_list_is_asked_for_again():
    result, _ = _assess_with(_EmptyThenFull())
    assert result.assessment.pathways
    assert any("asked again" in n for n in result.guardrail_notes)


def test_two_empty_pathway_lists_are_flagged_as_a_default_not_a_finding():
    result, _ = _assess_with(_EmptyThenFull(second_empty=True))
    assert not result.assessment.pathways
    assert any("default, not a finding" in n for n in result.guardrail_notes)


def test_a_code_requirement_is_met_when_the_chart_holds_the_code():
    from app.fhir.facts import Fact
    a = _assessment()
    a.general_requirements = [criteria.RequirementCheck(
        requirement="The request must include the CPT code for the requested procedure", status="unclear",
        policy_id=GENERAL_POLICY_ID, section="2.2", evidence=[], rationale="note has no code")]
    facts = [Fact(ref="ServiceRequest/sr-1", kind="ServiceRequest", date="2026-04-02",
                  text="ServiceRequest/sr-1 (2026-04-02): MRI right knee without contrast [CPT 73721]")]
    chunks = [{"policy_id": GENERAL_POLICY_ID, "section": "2.2", "heading": "x"}]
    clean, notes = criteria.validate(a.model_copy(update={"pathways": []}), "no codes here", chunks, facts)
    assert clean.general_requirements[0].status == "met"
    assert any("upgraded to met" in n for n in notes)


def test_draft_input_marks_chart_settled_requirements():
    a = _assessment()
    r = a.pathways[0].requirements[0]
    r.status, r.evidence_sources = "unclear", ["Observation/obs-2"]
    view = criteria.summarize_for_draft(criteria.AssessmentResult(assessment=a, recommendation="needs_more_info"))
    assert view["pathways"][0]["requirements"][0]["settled_by_chart"] is True


def _knee_with_prerequisite(prereq_status, meniscal_status):
    prereq = {"name": "Radiograph prerequisite", "policy_id": "MP-IMG-002", "section": "3.1",
              "requirements": [_req("Radiographs within 60 days", prereq_status, "3.1", "positive McMurray test")]}
    meniscal = _criteria()["pathways"][0]
    for r in meniscal["requirements"]:
        r["status"] = meniscal_status
    return criteria.CriteriaAssessment.model_validate(_criteria(pathways=[prereq, meniscal]))


def test_a_met_prerequisite_is_not_an_approval_pathway():
    """Regression: 3.1 (radiograph prerequisite) was met from the chart and approved a case with unclear real pathways."""
    a, notes = criteria.validate(_knee_with_prerequisite("met", "unclear"), NOTE, _policy_chunks())
    assert [p.section for p in a.pathways] == ["3.2"]
    assert any("prerequisite is not an approval pathway" in n for n in notes)
    assert criteria.decide(a) == "needs_more_info"


def test_an_unmet_prerequisite_stops_a_met_pathway_from_being_likely_meets():
    a, _ = criteria.validate(_knee_with_prerequisite("unclear", "met"), NOTE, _policy_chunks())
    assert criteria.decide(a) == "needs_more_info"


def test_draft_input_leaves_out_pathways_the_record_has_ruled_out():
    a = _assessment()
    a.pathways[0].requirements[0].status = "unclear"
    ruled_out = a.pathways[0].model_copy(deep=True)
    ruled_out.section, ruled_out.name = "3.3", "Suspected ligament injury"
    ruled_out.requirements[0].status = "not_met"
    a.pathways.append(ruled_out)
    view = criteria.summarize_for_draft(criteria.AssessmentResult(assessment=a, recommendation="needs_more_info"))
    assert [p["cite"] for p in view["pathways"]] == ["MP-IMG-002 section 3.2"]


class _TruncatedFirst(FakeLLM):
    """First criteria call stops at max_tokens (with a partial answer); the second is complete."""

    def create(self, **kwargs):
        message = super().create(**kwargs)
        if kwargs["tools"][0]["name"] == "record_criteria":
            message.stop_reason = "max_tokens" if self.calls.count("record_criteria") == 1 else "tool_use"
        return message


def test_a_truncated_assessment_is_retried_and_says_why():
    result, _ = _assess_with(_TruncatedFirst())
    assert any("cut off at the token limit" in n for n in result.guardrail_notes)


def test_the_assessment_has_room_to_finish():
    assert criteria.MAX_TOKENS >= 8000


def test_general_requirements_carry_their_own_citation_into_the_draft_input():
    a = _assessment()
    view = criteria.summarize_for_draft(criteria.AssessmentResult(assessment=a, recommendation="likely_meets"))
    assert all(g["cite"].startswith(("MP-", "GEN")) or "section" in g["cite"] for g in view["general_requirements"])
    assert view["general_requirements"][0]["cite"] == f"{GENERAL_POLICY_ID} section 2.4"
