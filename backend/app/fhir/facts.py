"""Turns FHIR resources into short, citable facts.

The text of a fact is produced here, by code, never by a model. The criteria agent may quote a fact
verbatim as evidence, and that quote is verified against this text, exactly as note quotes are
verified against the note. Patient names and addresses are deliberately left out (minimum necessary).
"""

from typing import Optional

from pydantic import BaseModel

CPT = "cpt"
ICD10 = "icd-10"


class Fact(BaseModel):
    ref: str  # "Procedure/proc-1": the FHIR resource this fact was built from
    kind: str  # patient, condition, medication, procedure, exam, imaging, order
    date: Optional[str] = None  # YYYY-MM-DD, used for sorting and recency
    text: str


def _display(concept: Optional[dict]) -> str:
    if not concept:
        return ""
    if concept.get("text"):
        return concept["text"]
    return next((c["display"] for c in concept.get("coding", []) if c.get("display")), "")


def _code(concept: Optional[dict], marker: str) -> Optional[str]:
    for c in (concept or {}).get("coding", []):
        if marker in c.get("system", "").lower():
            return c.get("code")
    return None


def _tags(concept: Optional[dict]) -> str:
    out = []
    cpt, icd = _code(concept, CPT), _code(concept, ICD10)
    if cpt:
        out.append(f"CPT {cpt}")
    if icd:
        out.append(f"ICD-10 {icd}")
    return f" [{', '.join(out)}]" if out else ""


def _day(value: Optional[str]) -> Optional[str]:
    return value[:10] if value else None


def _who(resource: dict) -> str:
    candidates = [
        resource.get("requester", {}).get("display"),
        *(p.get("display") or p.get("actor", {}).get("display") for p in resource.get("performer", [])),
    ]
    name = next((c for c in candidates if c), "")
    return f", by {name}" if name else ""


def _when(resource: dict) -> Optional[str]:
    for key in ("effectiveDateTime", "performedDateTime", "authoredOn", "onsetDateTime", "recordedDate", "issued"):
        if resource.get(key):
            return _day(resource[key])
    for key in ("effectivePeriod", "performedPeriod"):
        if resource.get(key, {}).get("start"):
            return _day(resource[key]["start"])
    return None


def _span(resource: dict) -> str:
    period = resource.get("performedPeriod") or resource.get("effectivePeriod") or {}
    start, end = _day(period.get("start")), _day(period.get("end"))
    if start and end:
        return f"{start} to {end}"
    return start or _when(resource) or "date unknown"


def _value(obs: dict) -> str:
    if "valueString" in obs:
        return obs["valueString"]
    if "valueCodeableConcept" in obs:
        return _display(obs["valueCodeableConcept"])
    if "valueQuantity" in obs:
        q = obs["valueQuantity"]
        return f"{q.get('value')} {q.get('unit', '')}".strip()
    if "valueBoolean" in obs:
        return "yes" if obs["valueBoolean"] else "no"
    return ""


def _reasons(resource: dict) -> str:
    reasons = [f"{_display(r)}{_tags(r)}" for r in resource.get("reasonCode", [])]
    return f", reason: {'; '.join(reasons)}" if reasons else ""


def _notes(resource: dict) -> str:
    text = " ".join(n.get("text", "") for n in resource.get("note", []) if n.get("text"))
    return f" Note: {text}" if text else ""


def summarize(resource: dict) -> Optional[Fact]:
    """One FHIR resource in, one fact out (None for resource types we do not use)."""
    rtype, rid = resource.get("resourceType"), resource.get("id", "?")
    ref = f"{rtype}/{rid}"
    when = _when(resource)
    if rtype == "Patient":
        ids = ", ".join(i.get("value", "") for i in resource.get("identifier", []))
        text = f"{ref}: {resource.get('gender', 'unknown sex')}, born {resource.get('birthDate', 'unknown')}, identifier {ids}"
        return Fact(ref=ref, kind="patient", date=None, text=text)
    if rtype == "Condition":
        status = _display(resource.get("clinicalStatus")) or "status unknown"
        text = f"{ref} (onset {when or 'unknown'}): {_display(resource.get('code'))}{_tags(resource.get('code'))}, {status}"
        return Fact(ref=ref, kind="condition", date=when, text=text)
    if rtype == "MedicationRequest":
        dose = "; ".join(d.get("text", "") for d in resource.get("dosageInstruction", []) if d.get("text"))
        med = _display(resource.get("medicationCodeableConcept"))
        text = f"{ref} ({when or 'date unknown'}): {med}{', ' + dose if dose else ''}{_who(resource)}, status {resource.get('status', 'unknown')}"
        return Fact(ref=ref, kind="medication", date=when, text=text + _notes(resource))
    if rtype == "Procedure":
        outcome = _display(resource.get("outcome"))
        text = (
            f"{ref} ({_span(resource)}): {_display(resource.get('code'))}{_tags(resource.get('code'))}"
            f"{_who(resource)}, status {resource.get('status', 'unknown')}."
        )
        if outcome:
            text += f" Outcome: {outcome}."
        return Fact(ref=ref, kind="procedure", date=when, text=text + _notes(resource))
    if rtype == "Observation":
        text = f"{ref} ({when or 'date unknown'}): {_display(resource.get('code'))}: {_value(resource)}{_who(resource)}"
        return Fact(ref=ref, kind="exam", date=when, text=text)
    if rtype == "DiagnosticReport":
        conclusion = resource.get("conclusion", "")
        text = f"{ref} ({when or 'date unknown'}): {_display(resource.get('code'))}{_tags(resource.get('code'))}."
        if conclusion:
            text += f" Conclusion: {conclusion}"
        return Fact(ref=ref, kind="imaging", date=when, text=text)
    if rtype == "ServiceRequest":
        text = (
            f"{ref} ({when or 'date unknown'}): {_display(resource.get('code'))}{_tags(resource.get('code'))}"
            f"{_reasons(resource)}{_who(resource)}, status {resource.get('status', 'unknown')}"
        )
        return Fact(ref=ref, kind="order", date=when, text=text)
    return None
