import json
import logging
from functools import lru_cache
from typing import Literal

from fastapi import FastAPI, HTTPException, Query

from .agents.intake import run_intake
from .config import settings
from .schemas import IntakeRequest, IntakeResponse

logger = logging.getLogger("priorauth")

app = FastAPI(
    title="Northbridge Prior Authorization Copilot",
    description="Assists human reviewers. Synthetic data only. Not a clinical decision system.",
    version="0.2.0",
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


@lru_cache(maxsize=1)
def _embedder():
    from .rag.embedder import get_embedder

    return get_embedder("local")


@app.get("/policy/search")
def policy_search(
    q: str = Query(min_length=3, description="Question about payer policy"),
    mode: Literal["vector", "keyword", "hybrid"] = "hybrid",
    k: int = Query(5, ge=1, le=20),
):
    """Search payer policy chunks. Each hit carries policy id, section and page for citation."""
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="DATABASE_URL is not configured")
    try:
        from .rag import search, store

        with store.connect() as conn:
            hits = search.search(conn, _embedder(), q, top_k=k, mode=mode)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Policy search failed")
        raise HTTPException(status_code=503, detail=f"Policy search unavailable: {exc}") from exc
    return {"query": q, "mode": mode, "results": hits}
