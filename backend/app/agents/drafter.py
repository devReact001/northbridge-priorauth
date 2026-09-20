"""Drafting agent: writes the document a reviewer will approve, edit or reject.

It sees only the structured, already-verified facts (intake record and assessment), never the
raw note, so it cannot pick up unverified text. A code check flags any procedure or diagnosis
code in the draft that is not present in those inputs.
"""

import json
import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from ..schemas import IntakeResult
from .llm import ToolCall, call_tool

DraftKind = Literal["submission_letter", "information_request", "denial_risk_memo"]

KIND_BY_RECOMMENDATION = {
    "likely_meets": "submission_letter",
    "needs_more_info": "information_request",
    "likely_not_meets": "denial_risk_memo",
}

INSTRUCTIONS = {
    "submission_letter": (
        "Write a prior authorization request letter to the payer. State the requested procedure and codes, "
        "then explain which policy pathway is met, citing the policy id and section for each criterion and "
        "using the supplied evidence quotes. Mention the general requirements that are satisfied."
    ),
    "information_request": (
        "Write a short message to the ordering clinician asking for the specific missing or unclear items "
        "listed in the assessment, one clear request per item, each tied to the policy section that needs it. "
        "Do not draft a submission."
    ),
    "denial_risk_memo": (
        "Write an internal memo for the reviewer explaining why the request is unlikely to meet policy, "
        "citing the policy sections and the facts, and listing what would change the outcome. Do not draft a "
        "submission letter."
    ),
}

SYSTEM_PROMPT = """You draft documents for a hospital prior-authorization team. A human reviewer will read,
edit and approve or reject your draft; nothing is sent automatically.

Rules:
- Use ONLY the facts in the supplied intake record and assessment. Never invent clinical facts, dates,
  names, codes or policy sections.
- Where information is unknown, write a bracketed placeholder such as [ordering provider name].
- Evidence quotes come with quote_sources. "note" means the clinical note. Any other value (for example
  "Procedure/proc-1") is a record from the patient's chart: attribute those facts to "the patient's medical
  record", never to the note.
- For an information request, ask only about requirements whose status is unclear or not_met and that the
  chart quotes do not already settle. Never ask about a requirement marked settled_by_chart, or about a
  requirement that is met. Never ask the clinician to repeat or perform an examination; ask them to
  document what is missing. Facts the chart already holds may be mentioned as context, not requested again.
- Every requirement carries its own "cite" value. Use that exact citation for it, and never cite a section you
  were not given.
- Cite policy sections in the form (MP-IMG-002 section 3.2).
- Anything the assessment says is not documented must be described as "not documented", never as "not done"
  or "not obtained".
- You assist the reviewer; you never decide coverage. Do not write that a request "should be denied" or
  "should be approved". Say "unlikely to meet", "appears to meet" or "needs more information", and leave the
  decision to the reviewer.
- Plain text only: no markdown, no asterisks, no bold. Use simple line breaks and hyphen lists.
- Plain professional tone, under 300 words."""


class Draft(BaseModel):
    subject: str
    body: str = Field(description="The full text of the document")


class DraftResult(BaseModel):
    kind: DraftKind
    subject: str
    body: str
    warnings: list[str] = Field(default_factory=list)


TOOL = {
    "name": "record_draft",
    "description": "Record the drafted document.",
    "input_schema": Draft.model_json_schema(),
}

CPT_RE = re.compile(r"\b\d{5}\b")
ICD_RE = re.compile(r"\b[A-TV-Z]\d{2}\.\d{1,4}\b")


def check_codes(body: str, allowed_text: str) -> list[str]:
    """Flag any CPT- or ICD-shaped code in the draft that does not appear in the source data."""
    allowed = set(CPT_RE.findall(allowed_text)) | set(ICD_RE.findall(allowed_text))
    found = set(CPT_RE.findall(body)) | set(ICD_RE.findall(body))
    return [f"Draft mentions code {c}, which is not in the source data" for c in sorted(found - allowed)]


def draft(
    kind: DraftKind,
    intake: IntakeResult,
    assessment_summary: dict[str, Any],
    policy_text: str,
    client: Optional[Any] = None,
    model: Optional[str] = None,
) -> tuple[DraftResult, ToolCall]:
    intake_json = intake.model_dump_json(indent=1)
    assessment_json = json.dumps(assessment_summary, indent=1)
    user = (
        f"Document to write: {kind}\n{INSTRUCTIONS[kind]}\n\n"
        f"<intake_record>\n{intake_json}\n</intake_record>\n\n"
        f"<assessment>\n{assessment_json}\n</assessment>"
    )
    call = call_tool(system=SYSTEM_PROMPT, user=user, tool=TOOL, client=client, model=model, max_tokens=1500)
    d = Draft.model_validate(call.data)
    d.body = d.body.replace("**", "")
    d.subject = d.subject.replace("**", "")
    warnings = check_codes(d.body, intake_json + assessment_json + policy_text)
    return DraftResult(kind=kind, subject=d.subject, body=d.body, warnings=warnings), call
