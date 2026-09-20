import hmac
import json
import logging
import re
import threading
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from .agents.intake import run_intake
from .config import settings
from .schemas import IntakeRequest, IntakeResponse
from .workflow.state import ReviewDecision

logger = logging.getLogger("priorauth")

_warm = threading.Event()
_warm_error: list[str] = []


def _warm_up() -> None:
    """Runs in a background thread at startup when WARMUP_ON_START is set. /ready reports the outcome."""
    from .workflow import runtime

    try:
        _workflow()  # also proves the service is configured (keys, database) before any traffic arrives
        runtime.warm_up()
        _warm.set()
        logger.info("Warm-up finished; the API is ready")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Warm-up failed")
        _warm_error.append(str(exc.detail if isinstance(exc, HTTPException) else f"{type(exc).__name__}: {exc}"))


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.warmup_on_start:
        threading.Thread(target=_warm_up, name="warm-up", daemon=True).start()
    yield


app = FastAPI(
    title="Northbridge Prior Authorization Copilot",
    description="Assists human reviewers. Synthetic data only. Not a clinical decision system.",
    version="0.6.0",
    lifespan=lifespan,
)


def require_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    """Shared-secret check. Skipped when API_KEY is not configured (local development)."""
    expected = settings.api_key
    if expected and not hmac.compare_digest(x_api_key or "", expected):
        raise HTTPException(status_code=401, detail="Missing or invalid API key")


AUTH = [Depends(require_api_key)]


@app.get("/health")
def health():
    """Liveness: the process is up. Says nothing about whether it can serve a case; see /ready."""
    return {"status": "ok", "model": settings.anthropic_model}


def _db_ok() -> bool:
    if not settings.database_url:
        return False
    from .rag import store

    try:
        with store.connect() as conn:
            conn.execute("SELECT 1")
        return True
    except Exception:  # noqa: BLE001
        return False


@app.get("/ready")
def ready():
    """Readiness: safe to send a reviewer's case here. The database answers and, if warm-up is on, the models are
    loaded. Kubernetes holds traffic back until this returns 200."""
    if not _db_ok():
        raise HTTPException(status_code=503, detail="The database is not reachable")
    if settings.warmup_on_start and not _warm.is_set():
        raise HTTPException(status_code=503, detail=_warm_error[-1] if _warm_error else "Models are still loading")
    return {"status": "ready"}


def _save_run(req: IntakeRequest, resp: IntakeResponse) -> None:
    """Best-effort persistence. The API must still work if the database is down."""
    if not settings.database_url:
        return
    try:
        import psycopg

        with psycopg.connect(settings.database_url) as conn:
            conn.execute(
                """INSERT INTO intake_runs
                   (source_name, raw_text, result, model, latency_ms, input_tokens, output_tokens)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (
                    req.source_name,
                    req.text,
                    json.dumps(resp.result.model_dump()),
                    resp.model,
                    resp.latency_ms,
                    resp.input_tokens,
                    resp.output_tokens,
                ),
            )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to persist intake run")


@app.post("/intake", response_model=IntakeResponse, dependencies=AUTH)
def intake(req: IntakeRequest):
    if not settings.anthropic_api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY is not configured")
    try:
        resp = run_intake(req.text)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    _save_run(req, resp)
    return resp


# ---------------------------------------------------------------- policy search (Week 2)

@lru_cache(maxsize=1)
def _embedder():
    from .rag.embedder import get_embedder

    return get_embedder("local")


@lru_cache(maxsize=1)
def _reranker():
    from .rag.reranker import get_reranker

    return get_reranker()


@app.get("/policy/search", dependencies=AUTH)
def policy_search(
    q: str = Query(min_length=3, description="Question about payer policy"),
    mode: str = "vector",
    k: int = Query(5, ge=1, le=20),
):
    """Search payer policy chunks. Each hit carries policy id, section and page for citation."""
    from .rag import search, store

    if mode not in search.STRATEGIES:
        raise HTTPException(status_code=422, detail=f"mode must be one of: {', '.join(search.MODES)}")
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="DATABASE_URL is not configured")
    try:
        reranker = _reranker() if search.STRATEGIES[mode].rerank else None
        with store.connect() as conn:
            hits = search.search(conn, _embedder(), q, top_k=k, mode=mode, reranker=reranker)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Policy search failed")
        raise HTTPException(status_code=503, detail=f"Policy search unavailable: {exc}") from exc
    return {"query": q, "mode": mode, "results": hits}


# ---------------------------------------------------------------- case workflow (Week 3, served to the UI in Week 5)

DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
SAMPLES_DIR = Path(__file__).resolve().parent / "data" / "sample_notes"


class NewCase(BaseModel):
    text: str = Field(min_length=20, description="Clinical note text")
    source_name: Optional[str] = None
    request_date: Optional[str] = Field(None, pattern=DATE_PATTERN, description="YYYY-MM-DD, defaults to today")


# Cases that are still running in the background, or that failed. A running case is invisible to the database
# until it finishes, so the API remembers it here. Lost on restart, which is fine: a restart also stops the run.
_running: dict[str, dict] = {}
_running_lock = threading.Lock()


def _public(view: dict) -> dict:
    return {k: v for k, v in view.items() if k != "state"}


def _persist(view: dict) -> None:
    from .workflow.runtime import persist_view

    persist_view(view)


def _workflow():
    if not settings.anthropic_api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY is not configured")
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="DATABASE_URL is not configured (needed for policy retrieval)")
    from .workflow.runtime import get_workflow

    return get_workflow()


def _saved_state(case_id: str) -> Optional[dict]:
    """A finished or paused case from the database, for when the live checkpointer no longer has it."""
    if not settings.database_url:
        return None
    from .rag import store
    from .workflow import persist

    try:
        with store.connect() as conn:
            persist.ensure_tables(conn)
            return persist.load_case(conn, case_id)
    except Exception:  # noqa: BLE001
        logger.exception("Could not load case %s from the database", case_id)
        return None


def _list_saved(status: Optional[str], limit: int) -> list[dict]:
    from .rag import store
    from .workflow import persist

    with store.connect() as conn:
        persist.ensure_tables(conn)
        return persist.list_cases(conn, status, limit)


def _metrics_cases(days: int) -> list[dict]:
    from .rag import store
    from .workflow import persist

    with store.connect() as conn:
        persist.ensure_tables(conn)
        return persist.load_for_metrics(conn, days)


def _run_case(case_id: str, text: str, source_name: Optional[str], request_date: Optional[str]) -> dict:
    """Run the workflow to the human-review pause. Runs in the background so the UI can show progress."""
    from .workflow.graph import start_case

    try:
        view = start_case(_workflow(), text, source_name, request_date, case_id=case_id)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Case %s failed", case_id)
        detail = exc.detail if isinstance(exc, HTTPException) else f"{type(exc).__name__}: {exc}"
        with _running_lock:
            _running[case_id] = {"state": "failed", "error": str(detail)}
        return {"case_id": case_id, "status": "failed", "error": str(detail)}
    _persist(view)
    with _running_lock:
        _running.pop(case_id, None)
    return _public(view)


@app.post("/cases", status_code=202, dependencies=AUTH)
def create_case(req: NewCase, background: BackgroundTasks, wait: bool = False):
    """Start a case. It runs until it pauses for human review; nothing is approved automatically.

    By default this returns at once with the case id (a run takes about a minute), and the caller polls
    GET /cases/{id}. Pass wait=true to block and get the finished packet back.
    """
    from .workflow.graph import new_case_id

    _workflow()  # fail fast with a clear 503 if the service is not configured
    case_id = new_case_id()
    with _running_lock:
        _running[case_id] = {"state": "running", "source_name": req.source_name}
    if wait:
        return _run_case(case_id, req.text, req.source_name, req.request_date)
    background.add_task(_run_case, case_id, req.text, req.source_name, req.request_date)
    return {"case_id": case_id, "status": "in_progress"}


@app.get("/cases", dependencies=AUTH)
def list_cases(status: Optional[str] = None, limit: int = Query(50, ge=1, le=200)):
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="DATABASE_URL is not configured")
    cases = _list_saved(status, limit)
    with _running_lock:
        running = [{"case_id": cid, "status": "in_progress" if r["state"] == "running" else "failed",
                    "recommendation": None, "source_name": r.get("source_name"), "created_at": None, "updated_at": None}
                   for cid, r in _running.items()]
    if status:
        running = [r for r in running if r["status"] == status]
    return {"cases": running + cases}


@app.get("/cases/{case_id}", dependencies=AUTH)
def get_case(case_id: str):
    """The case as the reviewer sees it. Live cases come from the checkpointer; if the API restarted, the saved
    copy is returned read-only (resumable=false)."""
    from .workflow.graph import case_view, view_from_state

    with _running_lock:
        running = dict(_running.get(case_id) or {})
    if running.get("state") == "failed":
        return {"case_id": case_id, "status": "failed", "error": running["error"], "trace": [], "packet": None}

    view = None
    try:
        view = case_view(_workflow(), case_id)
    except HTTPException:
        view = None  # not configured for live work; the saved copy below may still answer
    if view is not None:
        return _public(view)

    saved = _saved_state(case_id)
    if saved is not None:
        awaiting = saved.get("status") in (None, "awaiting_review") and not saved.get("review")
        return _public(view_from_state(case_id, saved, awaiting=bool(awaiting), resumable=False))
    if running.get("state") == "running":
        return {"case_id": case_id, "status": "in_progress", "trace": [], "packet": None}
    raise HTTPException(status_code=404, detail="Case not found")


@app.post("/cases/{case_id}/review", dependencies=AUTH)
def review_case(case_id: str, decision: ReviewDecision):
    """A human reviewer approves, edits or rejects. This is the only way a case gets finalized."""
    from .workflow.graph import NotAwaitingReview, resume_case

    try:
        view = resume_case(_workflow(), case_id, decision.model_dump())
    except KeyError as exc:
        raise HTTPException(
            status_code=404,
            detail="Case not found in the running workflow. If the API restarted, use CHECKPOINTER=postgres "
                   "so paused cases survive a restart.",
        ) from exc
    except NotAwaitingReview as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _persist(view)
    return _public(view)


# ---------------------------------------------------------------- reviewer UI helpers (Week 5)

@app.get("/metrics", dependencies=AUTH)
def metrics(days: int = Query(30, ge=1, le=365)):
    """Aggregates for the observability dashboard, from saved cases and their trace events."""
    from .workflow import metrics as compute

    if not settings.database_url:
        raise HTTPException(status_code=503, detail="DATABASE_URL is not configured")
    try:
        cases = _metrics_cases(days)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Could not load cases for metrics")
        raise HTTPException(status_code=503, detail=f"Metrics unavailable: {exc}") from exc
    return {"days": days, **compute.compute(cases)}


@app.get("/samples", dependencies=AUTH)
def samples():
    """The synthetic sample notes, so the UI can start a case in one click."""
    out = []
    for path in sorted(SAMPLES_DIR.glob("*.txt")):
        text = path.read_text(encoding="utf-8")
        visit = re.search(r"Date of visit:\s*(\d{4}-\d{2}-\d{2})", text)
        out.append({"name": path.name, "text": text, "suggested_request_date": visit.group(1) if visit else None})
    return {"samples": out}
