"""Criteria agent: checks a clinical note against one payer policy.

The LLM does the reading (which requirements are met, with quotes). Everything that decides
what happens next is plain code: citations are validated against the policy text that was
supplied, quotes are verified against the note, and the recommendation is computed by
`decide()`, never by the model.
"""

import json
import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from ..schemas import Evidence, IntakeResult
from .intake import _norm
from .llm import ToolCall, call_tool

Status = Literal["met", "not_met", "unclear", "not_applicable"]
Recommendation = Literal["likely_meets", "needs_more_info", "likely_not_meets", "no_applicable_policy"]

# Sections of the general policy that a clinical note can satisfy (2.1 member/provider IDs
# and the timing sections are administrative and not in a clinical note).
GENERAL_POLICY_ID = "MP-GEN-001"
GENERAL_SECTIONS = {"2.2", "2.3", "2.4", "6"}


class RequirementCheck(BaseModel):
    requirement: str = Field(description="One requirement, in plain words")
    status: Status
    policy_id: str
    section: str = Field(description="Policy section number the requirement comes from, e.g. '3.2'")
    evidence: list[Evidence] = Field(default_factory=list, description="Verbatim quotes from the note")
    rationale: str = Field(description="One sentence explaining the status")


class Pathway(BaseModel):
    name: str = Field(description="Approval pathway, e.g. 'Radiculopathy with neurological findings'")
    policy_id: str
    section: str
    requirements: list[RequirementCheck]


class Exclusion(BaseModel):
    policy_id: str
    section: str
    reason: str
    basis: Literal["documented", "missing_documentation"] = Field(
        description="'documented' if the note affirmatively shows the excluded situation (for example a "
        "repeat scan, or a red flag explicitly absent in an acute problem). 'missing_documentation' if the "
        "exclusion applies only because something is absent from the note (for example no exam documented)."
    )
    source_quote: str = Field(
        description="Verbatim quote from the note that triggers the exclusion, or empty if basis is missing_documentation"
    )


class CriteriaAssessment(BaseModel):
    policy_applies: bool = Field(description="False if the policy does not cover the requested procedure")
    applicable_policy_id: Optional[str] = None
    pathways: list[Pathway] = Field(default_factory=list)
    exclusions_triggered: list[Exclusion] = Field(default_factory=list)
    general_requirements: list[RequirementCheck] = Field(default_factory=list)
    summary: str = Field(description="Two or three sentences for a human reviewer")


class AssessmentResult(BaseModel):
    assessment: CriteriaAssessment
    recommendation: Recommendation
    guardrail_notes: list[str] = Field(default_factory=list)


SYSTEM_PROMPT = """You are the criteria-checking step of a prior-authorization assistant.
You receive: (1) a structured intake record, (2) the full clinical note, and (3) the complete text of
the payer policy that may apply, with every section labelled by policy id and section number.

Tasks:
1. Decide whether the policy covers the requested procedure. If it does not, set policy_applies to false
   and stop.
2. Otherwise list every approval pathway in the policy (each criteria section such as 3.1, 3.2 ...). Break
   each pathway into its requirements and mark each one met, not_met or unclear.
3. List any exclusions (the policy's exclusions section) that the note triggers.
4. Check the general requirements supplied (documentation of conservative therapy, note age, laterality,
   codes) and mark each met, not_met or unclear.

Rules:
- Mark met only when the note explicitly supports the requirement, and give verbatim quotes copied exactly
  from the note.
- Use unclear when the note is silent, ambiguous, limited or self-reported without clinician documentation.
  Missing documentation is never a reason for not_met: a note that does not mention radiographs, or says
  the exam was limited, makes those requirements unclear, because the information may exist elsewhere.
- Use not_met only when the note affirmatively shows the requirement is not satisfied (for example therapy
  documented as shorter than required, a Lachman test documented as negative, or a red flag explicitly
  denied). A not_met needs a verbatim quote that shows this. If you have no such quote, use unclear.
- Give quotes only when they support the requirement's status. Leave evidence empty otherwise.
- An exclusion whose wording is about something being absent (for example "no physical examination
  documented", "without documented findings") is ALWAYS missing_documentation, even if the note says the
  exam was limited or skipped. Use 'documented' only for a situation the note states directly, and give the
  exact quote.
- For each exclusion set basis: 'documented' when the note itself shows the excluded situation,
  'missing_documentation' when the exclusion applies only because something is absent from the note.
- Summary: two or three plain sentences. Say "not documented" rather than "not done" for anything the note
  does not mention. Do not use "however" to introduce a requirement that is met.
- not_applicable is only for the general requirements, when the requirement does not apply to this kind of
  procedure (for example laterality for a spine study). Never use it for a pathway requirement.
- Cite the policy id and section number for every requirement. Cite only sections that were provided.
- Do NOT decide coverage or say whether the request should be approved. The system computes the
  recommendation from your findings. A human reviewer makes the final decision."""

TOOL = {
    "name": "record_criteria",
    "description": "Record the criteria assessment of the note against the policy.",
    "input_schema": CriteriaAssessment.model_json_schema(),
}


CPT_IN_NOTE = re.compile(r"CPT[^\n]{0,20}?\b\d{5}\b", re.IGNORECASE)
ICD_IN_NOTE = re.compile(r"\b[A-TV-Z]\d{2}(?:\.\d{1,4})?\b")


def codes_present(requirement: str, note: str) -> bool:
    """True when a requirement that is only about billing codes is satisfied by codes written in the note.

    Code presence is a fact the code can check directly, so it does not depend on the model quoting it.
    """
    text = requirement.lower()
    wants_cpt, wants_icd = "cpt" in text, "icd" in text
    if not (wants_cpt or wants_icd):
        return False
    return (not wants_cpt or bool(CPT_IN_NOTE.search(note))) and (not wants_icd or bool(ICD_IN_NOTE.search(note)))


def format_policy_context(chunks: list[dict]) -> str:
    parts = []
    for c in chunks:
        body = c["content"].split("\n", 1)[-1]  # drop the retrieval header line
        parts.append(f"[{c['policy_id']} section {c['section']} - {c['heading']}]\n{body}")
    return "\n\n".join(parts)


def pathway_status(pathway: Pathway) -> Status:
    statuses = [r.status for r in pathway.requirements]
    if not statuses:
        return "unclear"
    if any(s == "not_met" for s in statuses):
        return "not_met"
    if all(s == "met" for s in statuses):
        return "met"
    return "unclear"


def decide(a: CriteriaAssessment) -> Recommendation:
    """Deterministic recommendation. Pure function: easy to test, explain and audit."""
    if not a.policy_applies:
        return "no_applicable_policy"
    statuses = [pathway_status(p) for p in a.pathways]
    if not statuses:
        return "needs_more_info"
    if any(s == "met" for s in statuses):
        if a.exclusions_triggered:
            return "needs_more_info"  # pathway and exclusion both triggered: a human must resolve
        if any(r.status not in ("met", "not_applicable") for r in a.general_requirements):
            return "needs_more_info"  # medically necessary but the request would be pended
        return "likely_meets"
    # A "not met" recommendation needs affirmative evidence against the request: at least one pathway
    # requirement the note shows to be unmet (with a verified quote). An exclusion alone is not enough,
    # because the model can label a documentation gap ("exam limited") as an exclusion the note "documents".
    # With no affirmative failure, the case asks for information instead.
    if any(e.basis == "documented" for e in a.exclusions_triggered) and any(s == "not_met" for s in statuses):
        return "likely_not_meets"
    if any(s == "unclear" for s in statuses) or a.exclusions_triggered:
        return "needs_more_info"
    return "likely_not_meets"


def validate(a: CriteriaAssessment, note_text: str, chunks: list[dict]) -> tuple[CriteriaAssessment, list[str]]:
    """Guardrails between the model and the decision. Returns a sanitised copy plus notes."""
    a = a.model_copy(deep=True)
    notes: list[str] = []
    note = _norm(note_text)
    valid = {(c["policy_id"], c["section"]) for c in chunks}

    def check_requirement(r: RequirementCheck, where: str) -> None:
        if (r.policy_id, r.section) not in valid:
            notes.append(f"{where}: cited {r.policy_id} section {r.section}, which was not in the policy provided")
            r.status = "unclear"
        verified = []
        for ev in r.evidence:
            if _norm(ev.source_quote) in note:
                verified.append(ev)
            else:
                notes.append(f"{where}: dropped a quote that does not appear in the note: '{ev.source_quote[:60]}'")
        r.evidence = verified
        if r.status == "met" and not verified and not codes_present(r.requirement, note_text):
            notes.append(f"{where}: 'met' has no verified quote, downgraded to unclear")
            r.status = "unclear"
        if r.status == "not_met" and not verified:
            notes.append(f"{where}: 'not_met' has no verified quote (absence of documentation), set to unclear")
            r.status = "unclear"

    for p in a.pathways:
        for r in p.requirements:
            if r.status == "not_applicable":
                notes.append(f"{p.policy_id} {p.section} / {r.requirement[:40]}: 'not_applicable' is not allowed on a pathway requirement, set to unclear")
                r.status = "unclear"
            check_requirement(r, f"{p.policy_id} {p.section} / {r.requirement[:40]}")
    for r in a.general_requirements:
        check_requirement(r, f"general / {r.requirement[:40]}")
    for e in a.exclusions_triggered:
        quote = _norm(e.source_quote)
        if e.basis == "documented" and (not quote or quote not in note):
            # An exclusion the note itself shows must be backed by note text. Without a verified quote it
            # cannot count against the request; keep it visible and ask for information instead.
            notes.append(
                f"exclusion {e.policy_id} {e.section}: no verified quote in the note, treated as missing "
                "documentation instead of a documented exclusion"
            )
            e.basis = "missing_documentation"
    return a, notes


def assess(
    note_text: str,
    intake: IntakeResult,
    chunks: list[dict],
    request_date: str,
    client: Optional[Any] = None,
    model: Optional[str] = None,
) -> tuple[AssessmentResult, ToolCall]:
    user = (
        f"Request date: {request_date}\n\n"
        f"<intake_record>\n{intake.model_dump_json(indent=1)}\n</intake_record>\n\n"
        f"<clinical_note>\n{note_text}\n</clinical_note>\n\n"
        f"<policy>\n{format_policy_context(chunks)}\n</policy>"
    )
    call = call_tool(system=SYSTEM_PROMPT, user=user, tool=TOOL, client=client, model=model, max_tokens=4000)
    raw = CriteriaAssessment.model_validate(call.data)
    clean, notes = validate(raw, note_text, chunks)
    return AssessmentResult(assessment=clean, recommendation=decide(clean), guardrail_notes=notes), call


def summarize_for_draft(result: AssessmentResult) -> dict[str, Any]:
    """Compact, verified view of the assessment for the drafting agent."""
    a = result.assessment
    # When a pathway is met, the other pathways are irrelevant, and asking the clinician about them
    # (for example cauda equina symptoms on a request that already qualifies) would be noise.
    met = [p for p in a.pathways if pathway_status(p) == "met"]
    shown = met or a.pathways
    return {
        "recommendation": result.recommendation,
        "summary": a.summary,
        "pathways": [
            {
                "name": p.name,
                "cite": f"{p.policy_id} section {p.section}",
                "status": pathway_status(p),
                "requirements": [
                    {"requirement": r.requirement, "status": r.status, "rationale": r.rationale,
                     "quotes": [e.source_quote for e in r.evidence]}
                    for r in p.requirements
                ],
            }
            for p in shown
        ],
        "exclusions_triggered": [json.loads(e.model_dump_json()) for e in a.exclusions_triggered],
        "general_requirements": [
            {"requirement": r.requirement, "status": r.status, "rationale": r.rationale}
            for r in a.general_requirements
        ],
    }
