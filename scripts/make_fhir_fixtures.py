"""Generate the synthetic FHIR R4 patient bundles used by the Week 4 EHR integration.

    python scripts/make_fhir_fixtures.py

Writes one bundle per patient to backend/app/data/fhir/. All people, dates and clinicians are invented.
The sample notes in backend/app/data/sample_notes/ refer to these patients by their SYN- identifier, and each
patient's chart is written to match its note, with deliberate exceptions:

- SYN-00982 (note_02): the note is thin, the chart holds the radiograph, therapy, exam and order.
                       Locking/catching is recorded nowhere, so one real gap remains.
- SYN-04471 (note_06): the note looks complete, but the chart shows an MRI of the same knee two months earlier.
"""

import json
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "backend" / "app" / "data" / "fhir"
CPT = "http://www.ama-assn.org/go/cpt"
ICD10 = "http://hl7.org/fhir/sid/icd-10-cm"
CATEGORY = "http://terminology.hl7.org/CodeSystem/observation-category"
DIAG_SECTION = "http://terminology.hl7.org/CodeSystem/v2-0074"
MRN = "urn:northbridge:synthetic-mrn"


def concept(text, system=None, code=None):
    c = {"text": text}
    if system:
        c["coding"] = [{"system": system, "code": code, "display": text}]
    return c


def patient(syn, sex, born):
    return {"resourceType": "Patient", "id": f"pt-{syn[4:]}", "identifier": [{"system": MRN, "value": syn}],
            "gender": sex, "birthDate": born}


def condition(pid, rid, icd, text, onset):
    return {"resourceType": "Condition", "id": rid, "subject": {"reference": f"Patient/{pid}"},
            "clinicalStatus": concept("active"), "code": concept(text, ICD10, icd), "onsetDateTime": onset}


def med(pid, rid, text, dose, day, doctor):
    return {"resourceType": "MedicationRequest", "id": rid, "status": "active", "intent": "order",
            "subject": {"reference": f"Patient/{pid}"}, "authoredOn": day, "requester": {"display": doctor},
            "medicationCodeableConcept": concept(text), "dosageInstruction": [{"text": dose}]}


def therapy(pid, rid, text, start, end, who, outcome):
    return {"resourceType": "Procedure", "id": rid, "status": "completed", "subject": {"reference": f"Patient/{pid}"},
            "code": concept(text), "performedPeriod": {"start": start, "end": end},
            "performer": [{"actor": {"display": who}}], "outcome": concept(outcome)}


def exam(pid, rid, text, value, day, who):
    return {"resourceType": "Observation", "id": rid, "status": "final", "subject": {"reference": f"Patient/{pid}"},
            "category": [{"coding": [{"system": CATEGORY, "code": "exam"}]}], "code": concept(text),
            "effectiveDateTime": day, "valueString": value, "performer": [{"display": who}]}


def imaging(pid, rid, text, cpt, day, conclusion):
    return {"resourceType": "DiagnosticReport", "id": rid, "status": "final", "subject": {"reference": f"Patient/{pid}"},
            "category": [{"coding": [{"system": DIAG_SECTION, "code": "RAD"}]}], "code": concept(text, CPT, cpt),
            "effectiveDateTime": day, "conclusion": conclusion}


def order(pid, rid, text, cpt, icd, reason, day, doctor):
    return {"resourceType": "ServiceRequest", "id": rid, "status": "active", "intent": "order",
            "subject": {"reference": f"Patient/{pid}"}, "code": concept(text, CPT, cpt),
            "reasonCode": [concept(reason, ICD10, icd)], "authoredOn": day, "requester": {"display": doctor}}


def knee_exam(pid, prefix, day, who, rom=None):
    rows = [("Medial joint line tenderness", "present"), ("McMurray test", "positive"),
            ("Knee effusion", "mild"), ("Lachman test", "negative")]
    if rom:
        rows.append(("Range of motion", rom))
    return [exam(pid, f"{prefix}-{i}", t, v, day, who) for i, (t, v) in enumerate(rows, 1)]


NAIR, RAO, SHAH = "Dr. Priya Nair (MD)", "Dr. Arjun Rao (MD)", "Dr. Karan Shah (Orthopedics)"
MENON, KULKARNI = "R. Menon (PT, DPT)", "S. Kulkarni (PT, DPT)"
XR_KNEE = "XR right knee, 2 views, weight-bearing"
NO_FRACTURE = "No fracture. Joint spaces preserved."


def build() -> dict[str, list[dict]]:
    charts: dict[str, list[dict]] = {}

    p = "pt-01203"  # note_03: knee, meets criteria, chart agrees with the note
    charts["SYN-01203"] = [
        patient("SYN-01203", "male", "1984-09-14"),
        condition(p, "cond-1", "M25.561", "Pain in right knee", "2026-01-15"),
        med(p, "med-1", "Naproxen 500 mg tablet", "500 mg twice daily", "2026-01-29", NAIR),
        therapy(p, "proc-1", "Physical therapy, twice weekly", "2026-01-29", "2026-03-12", MENON,
                "Minimal improvement in pain and function after 6 weeks"),
        imaging(p, "dx-1", XR_KNEE, "73560", "2026-02-20", NO_FRACTURE),
        *knee_exam(p, "obs", "2026-03-12", NAIR, "0 to 120 degrees"),
        order(p, "sr-1", "MRI right knee without contrast", "73721", "M25.561", "Pain in right knee", "2026-03-12", NAIR),
    ]

    p = "pt-00417"  # note_01: lumbar radiculopathy, chart agrees with the note
    charts["SYN-00417"] = [
        patient("SYN-00417", "male", "1971-11-03"),
        condition(p, "cond-1", "M54.16", "Radiculopathy, lumbar region", "2025-11-10"),
        med(p, "med-1", "Naproxen 500 mg tablet", "500 mg twice daily", "2025-12-31", RAO),
        therapy(p, "proc-1", "Physical therapy, twice weekly", "2026-01-08", "2026-03-05", MENON,
                "Minimal improvement after 8 weeks"),
        exam(p, "obs-1", "Straight leg raise, left", "positive at 40 degrees", "2026-03-12", RAO),
        exam(p, "obs-2", "Sensation, left L5 dermatome", "decreased", "2026-03-12", RAO),
        exam(p, "obs-3", "Strength, left extensor hallucis longus", "4/5", "2026-03-12", RAO),
        order(p, "sr-1", "MRI lumbar spine without contrast", "72148", "M54.16", "Radiculopathy, lumbar region",
              "2026-03-12", RAO),
    ]

    p = "pt-00982"  # note_02: thin note; chart holds most of what is missing, but not locking/catching
    charts["SYN-00982"] = [
        patient("SYN-00982", "female", "1978-08-21"),
        condition(p, "cond-1", "M25.561", "Pain in right knee", "2026-01-20"),
        med(p, "med-1", "Ibuprofen 400 mg tablet", "400 mg three times daily as needed", "2026-02-10", RAO),
        therapy(p, "proc-1", "Physical therapy, twice weekly", "2026-02-16", "2026-03-30", KULKARNI,
                "Pain with stairs unchanged after 6 weeks of therapy"),
        imaging(p, "dx-1", "XR right knee, AP and lateral, weight-bearing", "73560", "2026-03-10", NO_FRACTURE),
        *knee_exam(p, "obs", "2026-03-24", SHAH, "0 to 125 degrees"),
        order(p, "sr-1", "MRI right knee without contrast", "73721", "M25.561", "Pain in right knee", "2026-04-02", RAO),
    ]

    p = "pt-02218"  # note_04: acute low back pain, no red flags, no therapy history
    charts["SYN-02218"] = [
        patient("SYN-02218", "male", "1992-12-05"),
        condition(p, "cond-1", "M54.50", "Low back pain, unspecified", "2026-03-06"),
        exam(p, "obs-1", "Straight leg raise", "negative bilaterally", "2026-03-20", RAO),
        exam(p, "obs-2", "Strength and sensation, both legs", "normal", "2026-03-20", RAO),
        order(p, "sr-1", "MRI lumbar spine without contrast", "72148", "M54.50", "Low back pain, unspecified",
              "2026-03-20", RAO),
    ]

    p = "pt-03377"  # note_05: chest CT, no payer policy covers it
    charts["SYN-03377"] = [
        patient("SYN-03377", "female", "1963-07-19"),
        condition(p, "cond-1", "R05.3", "Chronic cough", "2025-12-20"),
        med(p, "med-1", "Fluticasone inhaler", "2 puffs twice daily", "2026-01-10", NAIR),
        imaging(p, "dx-1", "XR chest, 2 views", "71046", "2026-03-01", "No acute cardiopulmonary abnormality."),
        order(p, "sr-1", "CT chest with contrast", "71260", "R05.3", "Chronic cough", "2026-03-25", NAIR),
    ]

    p = "pt-04471"  # note_06: looks complete, but the chart shows an MRI of the same knee two months earlier
    charts["SYN-04471"] = [
        patient("SYN-04471", "female", "1967-09-30"),
        condition(p, "cond-1", "M25.561", "Pain in right knee", "2025-12-01"),
        med(p, "med-1", "Naproxen 500 mg tablet", "500 mg twice daily", "2026-01-30", NAIR),
        therapy(p, "proc-1", "Physical therapy, twice weekly", "2026-02-02", "2026-03-16", MENON,
                "Minimal improvement after 6 weeks"),
        imaging(p, "dx-1", "MRI right knee without contrast", "73721", "2026-01-14",
                "Degenerative signal in the posterior horn of the medial meniscus without a displaced tear. "
                "Small joint effusion. No ligament injury."),
        imaging(p, "dx-2", XR_KNEE, "73560", "2026-03-02", NO_FRACTURE),
        *knee_exam(p, "obs", "2026-03-18", NAIR, "0 to 120 degrees"),
        order(p, "sr-1", "MRI right knee without contrast", "73721", "M25.561", "Pain in right knee", "2026-03-18", NAIR),
    ]
    return charts


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for syn, resources in build().items():
        bundle = {"resourceType": "Bundle", "type": "collection", "entry": [{"resource": r} for r in resources]}
        path = OUT / f"{syn}.json"
        path.write_text(json.dumps(bundle, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {path.name}: {len(resources)} resources")


if __name__ == "__main__":
    main()
