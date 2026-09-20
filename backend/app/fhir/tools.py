"""The read-only tool surface over a FHIR source.

This module is the single definition of the tools. The MCP server registers them, and the in-process
toolbox used by tests calls the same code, so what is tested is what is served.

Each tool takes only a patient identifier and returns compact facts. Nothing
here can write, and there is no free-form query tool, so an agent (or a prompt injection) cannot
reach outside these calls.
"""

from typing import Any, Optional

from .facts import Fact, summarize
from .source import FhirSource

MAX_FACTS = 25

# name -> (resource type, category filter, description)
TOOLS: dict[str, tuple[str, Optional[str], str]] = {
    "get_patient": ("Patient", None, "Basic demographics for the patient (sex, birth date, identifier). No name or address."),
    "get_conditions": ("Condition", None, "Diagnoses on the patient's problem list, with ICD-10 codes and onset dates."),
    "get_medications": ("MedicationRequest", None, "Medication orders with dose, prescriber, dates and status. Use for conservative drug therapy such as NSAIDs."),
    "get_procedures": ("Procedure", None, "Procedures and therapies performed, with dates, performer and outcome. Use for physical therapy, injections and surgery."),
    "get_exam_findings": ("Observation", "exam", "Physical examination findings recorded in the chart (for example McMurray test, straight leg raise, effusion)."),
    "get_imaging_reports": ("DiagnosticReport", "RAD", "Radiology reports (X-ray, MRI, CT) with dates and conclusions. Use to find prior imaging of the same body part."),
    "get_service_requests": ("ServiceRequest", None, "Orders placed for the patient, with CPT codes and the reason for each order."),
}

PARAM_DOC = {
    "patient": "Patient identifier exactly as written on the request, for example SYN-00982.",
}

# Deliberately no filter parameters (date range, keyword). An earlier version had a keyword filter and the agent
# hid evidence from itself: filtering exam findings by "knee" dropped "McMurray test: positive", and filtering
# procedures by "knee" dropped the physical therapy record. Results are already small (newest 25), so the
# criteria step gets everything and decides what is relevant.
INPUT_SCHEMA = {
    "type": "object",
    "properties": {k: {"type": "string", "description": v} for k, v in PARAM_DOC.items()},
    "required": ["patient"],
}


def tool_specs() -> list[dict]:
    """Tool definitions in the shape the Anthropic Messages API expects."""
    return [{"name": n, "description": d, "input_schema": INPUT_SCHEMA} for n, (_, _, d) in TOOLS.items()]


class FhirTools:
    def __init__(self, source: FhirSource):
        self.source = source

    def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name not in TOOLS:
            return {"error": f"unknown tool {name}", "facts": []}
        patient_ref = str(args.get("patient", "")).strip()
        if not patient_ref:
            return {"error": "patient is required", "facts": []}
        patient = self.source.find_patient(patient_ref)
        if patient is None:
            return {"error": "patient_not_found", "patient": patient_ref, "facts": []}
        resource_type, category, _ = TOOLS[name]
        if resource_type == "Patient":
            resources = [patient]
        else:
            resources = self.source.search(resource_type, patient["id"], category)
        facts: list[Fact] = [f for f in (summarize(r) for r in resources) if f]
        facts.sort(key=lambda f: f.date or "", reverse=True)
        return {
            "patient": patient_ref,
            "tool": name,
            "count": len(facts),
            "truncated": len(facts) > MAX_FACTS,
            "facts": [f.model_dump() for f in facts[:MAX_FACTS]],
        }
