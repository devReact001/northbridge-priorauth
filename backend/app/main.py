import json
import logging

from fastapi import FastAPI, HTTPException

from .agents.intake import run_intake
from .config import settings
from .schemas import IntakeRequest, IntakeResponse

logger = logging.getLogger("priorauth")

app = FastAPI(
    title="Northbridge Prior Authorization Copilot",
    description="Assists human reviewers. Synthetic data only. Not a clinical decision system.",
    version="0.1.0",
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
