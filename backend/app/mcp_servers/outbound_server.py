"""Write-side MCP server: the only place the system sends anything out.

    python -m app.mcp_servers.outbound_server

Kept apart from the read-only FHIR server on purpose: the two have different trust levels, so a client can be
given one without the other. Every tool needs the name of the human who approved the action, is idempotent per
case (calling it twice never sends twice), and validates its input. In this project the "payer portal" and the
"clinician inbox" are a local outbox folder; a real deployment would swap the two functions that write to it.
"""

import hashlib
import json
import logging
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP
except ImportError:  # mcp 2.x renamed it
    from mcp.server.mcpserver import MCPServer as FastMCP

from ..config import settings

CASE_ID = re.compile(r"[A-Za-z0-9_-]{1,40}")
CPT_CODE = re.compile(r"\d{5}")
MAX_TEXT = 20_000


class Outbox:
    """One JSON file per (case, action). Existence of the file is the idempotency record."""

    def __init__(self, directory: Path):
        self.directory = Path(directory)

    def _path(self, case_id: str, action: str) -> Path:
        if not CASE_ID.fullmatch(case_id):
            raise ValueError("invalid case_id")
        return self.directory / f"{case_id}__{action}.json"

    def existing(self, case_id: str, action: str) -> Optional[dict]:
        path = self._path(case_id, action)
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    def write(self, case_id: str, action: str, record: dict) -> None:
        path = self._path(case_id, action)
        self.directory.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(record, indent=1), encoding="utf-8")
        tmp.replace(path)


def _require(value: str, name: str) -> str:
    value = (value or "").strip()
    if not value:
        raise ValueError(f"{name} is required")
    if len(value) > MAX_TEXT:
        raise ValueError(f"{name} is too long")
    return value


def _reference(prefix: str, case_id: str) -> str:
    return f"{prefix}-{hashlib.sha1(case_id.encode()).hexdigest()[:8].upper()}"


def submit_prior_authorization(
    outbox: Outbox, case_id: str, patient: str, cpt: str, icd10: list[str], letter: str, approved_by: str
) -> dict[str, Any]:
    patient, letter, approved_by = _require(patient, "patient"), _require(letter, "letter"), _require(approved_by, "approved_by")
    if not CPT_CODE.fullmatch(cpt or ""):
        raise ValueError("cpt must be a 5-digit code")
    if not icd10:
        raise ValueError("at least one ICD-10 code is required")
    done = outbox.existing(case_id, "submission")
    if done:
        return {"status": "duplicate", "reference": done["reference"]}
    reference = _reference("PA", case_id)
    claim = {  # simplified FHIR R4 Claim, use = preauthorization
        "resourceType": "Claim", "status": "active", "use": "preauthorization",
        "identifier": [{"value": case_id}], "patient": {"identifier": {"value": patient}},
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "diagnosis": [
            {"sequence": i, "diagnosisCodeableConcept": {"coding": [{"system": "http://hl7.org/fhir/sid/icd-10-cm", "code": c}]}}
            for i, c in enumerate(icd10, 1)
        ],
        "item": [{"sequence": 1, "productOrService": {"coding": [{"system": "http://www.ama-assn.org/go/cpt", "code": cpt}]}}],
        "supportingInfo": [{"sequence": 1, "category": {"text": "letter of medical necessity"}, "valueString": letter}],
    }
    outbox.write(case_id, "submission", {"reference": reference, "approved_by": approved_by, "claim": claim})
    return {"status": "submitted", "reference": reference}


def send_clinician_message(
    outbox: Outbox, case_id: str, patient: str, subject: str, body: str, approved_by: str
) -> dict[str, Any]:
    patient, subject, body = _require(patient, "patient"), _require(subject, "subject"), _require(body, "body")
    approved_by = _require(approved_by, "approved_by")
    done = outbox.existing(case_id, "message")
    if done:
        return {"status": "duplicate", "reference": done["reference"]}
    reference = _reference("MSG", case_id)
    outbox.write(case_id, "message", {
        "reference": reference, "approved_by": approved_by, "patient": patient, "subject": subject, "body": body,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    return {"status": "sent", "reference": reference}


def build_server(outbox: Optional[Outbox] = None) -> FastMCP:
    box = outbox or Outbox(Path(settings.outbox_dir))
    server = FastMCP(
        "northbridge-outbound",
        instructions="Sends approved documents out. Every call needs the approving human's name and is idempotent per case.",
    )

    @server.tool(name="submit_prior_authorization", description="Submit an approved prior authorization letter to the payer. Needs a CPT code, ICD-10 codes and the approver's name.")
    def submit_prior_authorization_tool(
        case_id: str, patient: str, cpt: str, icd10: list[str], letter: str, approved_by: str
    ) -> dict[str, Any]:
        return submit_prior_authorization(box, case_id, patient, cpt, icd10, letter, approved_by)

    @server.tool(name="send_clinician_message", description="Send an approved information request to the ordering clinician. Needs the approver's name.")
    def send_clinician_message_tool(
        case_id: str, patient: str, subject: str, body: str, approved_by: str
    ) -> dict[str, Any]:
        return send_clinician_message(box, case_id, patient, subject, body, approved_by)

    return server


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    build_server().run(transport="stdio")


if __name__ == "__main__":
    main()
