import json
import logging
from functools import lru_cache
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from .agents.intake import run_intake
from .config import settings
from .schemas import IntakeRequest, IntakeResponse
from .workflow.state import ReviewDecision

logger = logging.getLogger("priorauth")

app = FastAPI(
    title="Northbridge Prior Authorization Copilot",
    description="Assists human reviewers. Synthetic data only. Not a clinical decision system.",
    version="0.3.0",
)


@app.get("/health")
def health():
    return {"status": "ok", "model": settings.anthropic_model}


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


@app.post("/intake", response_model=IntakeResponse)
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


@app.get("/policy/search")
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


# ---------------------------------------------------------------- case workflow (Week 3)

class NewCase(BaseModel):
    text: str = Field(min_length=20, description="Clinical note text")
    source_name: Optional[str] = None


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


@app.post("/cases")
def create_case(req: NewCase):
    """Run the workflow until it pauses for human review. Nothing is approved automatically."""
    from .workflow.graph import start_case

    view = start_case(_workflow(), req.text, req.source_name)
    _persist(view)
    return _public(view)


@app.get("/cases")
def list_cases(status: Optional[str] = None, limit: int = Query(50, ge=1, le=200)):
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="DATABASE_URL is not configured")
    from .rag import store
    from .workflow import persist

    with store.connect() as conn:
        persist.ensure_tables(conn)
        return {"cases": persist.list_cases(conn, status, limit)}


@app.get("/cases/{case_id}")
def get_case(case_id: str):
    from .workflow.graph import case_view

    view = case_view(_workflow(), case_id)
    if view is None:
        raise HTTPException(status_code=404, detail="Case not found (memory checkpointer forgets on restart)")
    return _public(view)


@app.post("/cases/{case_id}/review")
def review_case(case_id: str, decision: ReviewDecision):
    """A human reviewer approves, edits or rejects. This is the only way a case gets finalized."""
    from .workflow.graph import NotAwaitingReview, resume_case

    try:
        view = resume_case(_workflow(), case_id, decision.model_dump())
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Case not found") from exc
    except NotAwaitingReview as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _persist(view)
    return _public(view)
