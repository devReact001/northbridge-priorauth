"""Where FHIR data comes from. Two implementations behind one small interface:

- BundleFhirSource reads synthetic FHIR R4 bundles from a folder (offline, deterministic, used in tests and demos).
- HttpFhirSource talks to a real FHIR R4 REST API (a hospital EHR, or a public test server with fake data).

Both are read-only. There is no method that writes, and no free-form query, by design.
"""

import json
from pathlib import Path
from typing import Optional, Protocol

import httpx


class FhirSource(Protocol):
    def find_patient(self, ref: str) -> Optional[dict]: ...

    def search(self, resource_type: str, patient_id: str, category: Optional[str] = None) -> list[dict]: ...


def _patient_ref(resource: dict) -> Optional[str]:
    for key in ("subject", "patient"):
        ref = resource.get(key, {}).get("reference")
        if ref:
            return ref.split("/")[-1]
    return None


def _has_category(resource: dict, category: str) -> bool:
    codes = [c.get("code") for cat in resource.get("category", []) for c in cat.get("coding", [])]
    return category in codes


class BundleFhirSource:
    def __init__(self, directory: Path):
        self._by_type: dict[str, list[dict]] = {}
        for path in sorted(Path(directory).glob("*.json")):
            bundle = json.loads(path.read_text(encoding="utf-8"))
            for entry in bundle.get("entry", []):
                resource = entry["resource"]
                self._by_type.setdefault(resource["resourceType"], []).append(resource)

    def find_patient(self, ref: str) -> Optional[dict]:
        wanted = ref.strip().lower()
        for patient in self._by_type.get("Patient", []):
            values = [patient.get("id", ""), *(i.get("value", "") for i in patient.get("identifier", []))]
            if wanted in (v.lower() for v in values):
                return patient
        return None

    def search(self, resource_type: str, patient_id: str, category: Optional[str] = None) -> list[dict]:
        found = [r for r in self._by_type.get(resource_type, []) if _patient_ref(r) == patient_id]
        if category:
            found = [r for r in found if _has_category(r, category)]
        return found


class HttpFhirSource:
    """Minimal FHIR REST client. Follows only the first page of a search (capped by _count)."""

    def __init__(self, base_url: str, token: str = "", client: Optional[httpx.Client] = None, count: int = 50):
        headers = {"Accept": "application/fhir+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = client or httpx.Client(base_url=base_url.rstrip("/") + "/", headers=headers, timeout=10.0)
        self._count = count

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        response = self._client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    def find_patient(self, ref: str) -> Optional[dict]:
        bundle = self._get("Patient", {"identifier": ref, "_count": 1})
        entries = bundle.get("entry", [])
        if entries:
            return entries[0]["resource"]
        try:
            return self._get(f"Patient/{ref}")
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (400, 404):
                return None
            raise

    def search(self, resource_type: str, patient_id: str, category: Optional[str] = None) -> list[dict]:
        params: dict = {"patient": patient_id, "_count": self._count}
        if category:
            params["category"] = category
        bundle = self._get(resource_type, params)
        return [e["resource"] for e in bundle.get("entry", []) if e.get("resource", {}).get("resourceType") == resource_type]
