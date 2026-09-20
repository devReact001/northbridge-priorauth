"""Run the real FastAPI app on a scripted fake model, with synthetic dashboard data. No Claude key, no database.

For trying the UI and taking screenshots:   cd backend; python ../scripts/demo_api.py   (port 8000)
Everything on the dashboard here is DEMO data generated below, not real cases.
"""

import copy
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(BACKEND / "tests"))

import uvicorn  # noqa: E402
from app import main  # noqa: E402
from test_workflow import NOTE, FakeLLM, _graph  # noqa: E402
import tempfile  # noqa: E402


class SlowFakeLLM(FakeLLM):
    def create(self, **kwargs):
        time.sleep(0.8)
        return super().create(**kwargs)


_graph_holder = {}


def _workflow():
    if "g" not in _graph_holder:
        _graph_holder["g"] = _graph(SlowFakeLLM())
    return _graph_holder["g"]


def _demo_cases(n=60):
    rng = random.Random(7)
    now = datetime.utcnow()
    out = []
    for i in range(n):
        rec = rng.choices(["likely_meets", "needs_more_info", "likely_not_meets", "no_applicable_policy"], [50, 20, 15, 15])[0]
        action = rng.choices(["approve", "edit", "reject"], [60, 30, 10])[0]
        notes = []
        if rng.random() < 0.3:
            notes.append("dropped a quote that appears in neither the note nor the EHR facts: 'x'")
        if rng.random() < 0.15:
            notes.append("MP-IMG-002 3.1: a prerequisite is not an approval pathway, its requirements were moved")
        if rng.random() < 0.1:
            notes.append("the model was cut off at the token limit at first; asked again and it did")
        ev = [
            {"node": "intake", "latency_ms": rng.randint(3000, 9000), "input_tokens": 1200, "output_tokens": rng.randint(300, 700), "detail": {"unverified_quotes": 1 if rng.random() < 0.1 else 0}},
            {"node": "ehr", "latency_ms": rng.randint(800, 2500), "input_tokens": 0, "output_tokens": 0, "detail": {}},
            {"node": "assess", "latency_ms": rng.randint(30000, 60000), "input_tokens": 6000, "output_tokens": rng.randint(2500, 4500), "detail": {}},
            {"node": "draft", "latency_ms": rng.randint(8000, 20000), "input_tokens": 3000, "output_tokens": 800, "detail": {}},
            {"node": "human_review", "latency_ms": 0, "input_tokens": 0, "output_tokens": 0, "detail": {}},
        ]
        ehr = {"status": rng.choices(["ok", "patient_not_found", "error"], [85, 10, 5])[0], "facts": [{}] * rng.randint(0, 9)}
        dispatch = {"status": rng.choices(["sent", "blocked"], [80, 20])[0], "reason": "placeholders: [Ordering provider name]"}
        state = {"review": {"action": action}, "assessment": {"guardrail_notes": notes}, "ehr": ehr, "dispatch": dispatch}
        status = {"approve": "approved", "edit": "approved_with_edits", "reject": "rejected"}[action]
        out.append({"case_id": f"demo{i:03d}", "created_at": (now - timedelta(days=rng.randint(0, 27), hours=rng.randint(0, 12))).isoformat(),
                    "status": status, "recommendation": rec, "state": state, "events": ev})
    return out


_saved = {}  # finished demo cases, so the queue has something after a review


def _persist(view):
    _saved[view["case_id"]] = {"case_id": view["case_id"], "status": view["status"], "recommendation": view.get("recommendation"),
                               "source_name": view.get("source_name"), "created_at": datetime.utcnow().isoformat(),
                               "updated_at": datetime.utcnow().isoformat()}


def _list_saved(status, limit):
    rows = list(_saved.values())
    return [r for r in rows if not status or r["status"] == status][:limit]


# The fake model's quotes come from this note, so this is the sample that verifies cleanly in the demo.
_dir = Path(tempfile.mkdtemp())
(_dir / "note_demo_knee_mri.txt").write_text("SYNTHETIC NOTE - NOT A REAL PATIENT\n\nDate of visit: 2026-03-12\n\n" + NOTE, encoding="utf-8")
main.SAMPLES_DIR = _dir
main._list_saved = _list_saved
main._workflow = _workflow
main._persist = _persist
main._saved_state = lambda case_id: None
main._metrics_cases = lambda days: _demo_cases()
main.settings.database_url = "demo"

if __name__ == "__main__":
    print("DEMO MODE: scripted fake model, synthetic metrics. Not real cases.")
    uvicorn.run(main.app, host="127.0.0.1", port=8000, log_level="warning")
