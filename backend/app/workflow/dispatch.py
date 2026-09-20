"""What happens after a human approves: which outbound action (if any) the approved document triggers.

Pure functions, so the rules are easy to test and audit. Nothing is ever sent unless a reviewer approved or
edited the case (the graph only reaches this step after `human_review`), and every outbound call carries the
approving reviewer's name.

    submission_letter    -> submit to the payer
    information_request  -> message the ordering clinician
    denial_risk_memo     -> internal only, nothing is sent
"""

import re
from typing import Any, Optional

from .state import CaseState

CPT_IN_FACT = re.compile(r"\[[^\]]*CPT (\d{5})")
PLACEHOLDER = re.compile(r"\[[A-Za-z][A-Za-z .'/-]{2,60}\]")
ICD_IN_FACT = re.compile(r"ICD-10 ([A-Z]\d{2}(?:\.\d{1,4})?)")


def _order_codes(state: CaseState) -> tuple[Optional[str], list[str]]:
    """Codes from the chart's order, used only when the note itself did not state them."""
    cpt, icd = None, []
    for fact in state.get("ehr", {}).get("facts", []):
        if fact.get("kind") != "order":
            continue
        cpt = cpt or next(iter(CPT_IN_FACT.findall(fact["text"])), None)
        icd += [c for c in ICD_IN_FACT.findall(fact["text"]) if c not in icd]
    return cpt, icd


def plan(state: CaseState) -> dict[str, Any]:
    """Returns {"action": "skip" | "blocked" | "call", ...}."""
    review = state.get("review") or {}
    if review.get("action") not in ("approve", "edit"):
        return {"action": "skip", "reason": "The reviewer did not approve, so nothing is sent."}
    draft, document = state.get("draft"), state.get("final_document")
    if not draft or not document:
        return {"action": "skip", "reason": "There is no drafted document to send."}
    kind = draft["kind"]
    if kind == "denial_risk_memo":
        return {"action": "skip", "reason": "An internal memo: nothing is sent outside."}
    left = sorted(set(PLACEHOLDER.findall(document)))
    if left:
        # A drafted document leaves bracketed blanks for facts the system does not have. A person must fill
        # them in (choose Edit) before anything goes out; sending a letter that says "[Ordering provider name]"
        # would be a real submission with a hole in it.
        return {"action": "blocked",
                "reason": f"The document still has placeholders to fill in: {', '.join(left)}. Edit it, then approve."}
    intake = state["intake"]["result"]
    patient = intake.get("patient_ref")
    if not patient:
        return {"action": "blocked", "reason": "The note has no patient identifier to send against."}
    common = {"case_id": state["case_id"], "patient": patient, "approved_by": review["reviewer"]}
    if kind == "information_request":
        return {"action": "call", "tool": "send_clinician_message",
                "args": {**common, "subject": draft["subject"], "body": document}}
    chart_cpt, chart_icd = _order_codes(state)
    cpt = intake.get("procedure_code") or chart_cpt
    icd = intake.get("diagnosis_codes") or chart_icd
    if not cpt or not icd:
        return {"action": "blocked", "reason": "A submission needs a CPT code and at least one ICD-10 code."}
    return {"action": "call", "tool": "submit_prior_authorization",
            "args": {**common, "cpt": cpt, "icd10": icd, "letter": document}}
