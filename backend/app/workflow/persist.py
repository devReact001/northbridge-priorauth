"""Case and trace storage. The Week 5 dashboard reads these two tables."""

import json
from typing import Optional

import psycopg

DDL = """
CREATE TABLE IF NOT EXISTS cases (
    case_id        TEXT PRIMARY KEY,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    status         TEXT NOT NULL,
    recommendation TEXT,
    source_name    TEXT,
    state          JSONB NOT NULL
);
CREATE TABLE IF NOT EXISTS case_events (
    id            SERIAL PRIMARY KEY,
    case_id       TEXT NOT NULL REFERENCES cases(case_id) ON DELETE CASCADE,
    seq           INTEGER NOT NULL,
    ts            TIMESTAMPTZ,
    node          TEXT NOT NULL,
    latency_ms    INTEGER,
    input_tokens  INTEGER,
    output_tokens INTEGER,
    detail        JSONB
);
CREATE INDEX IF NOT EXISTS case_events_case_idx ON case_events (case_id, seq);
"""


def ensure_tables(conn: psycopg.Connection) -> None:
    conn.execute(DDL)


def save_case(conn: psycopg.Connection, view: dict) -> None:
    """Upsert the case and rewrite its events (a trace is small, so this stays simple)."""
    state = dict(view["state"])
    # Policy text is reproducible from the policy id, so store only which sections were used.
    state["policy_chunks"] = [f"{c['policy_id']} {c['section']}" for c in state.get("policy_chunks", [])]
    conn.execute(
        """INSERT INTO cases (case_id, status, recommendation, source_name, state)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (case_id) DO UPDATE
           SET status = EXCLUDED.status, recommendation = EXCLUDED.recommendation,
               state = EXCLUDED.state, updated_at = now()""",
        (view["case_id"], view["status"], view["recommendation"], state.get("source_name"),
         json.dumps(state, default=str)),
    )
    conn.execute("DELETE FROM case_events WHERE case_id = %s", (view["case_id"],))
    with conn.cursor() as cur:
        for seq, e in enumerate(view["trace"]):
            cur.execute(
                """INSERT INTO case_events
                   (case_id, seq, ts, node, latency_ms, input_tokens, output_tokens, detail)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (view["case_id"], seq, e["ts"], e["node"], e["latency_ms"], e["input_tokens"],
                 e["output_tokens"], json.dumps(e["detail"], default=str)),
            )


def list_cases(conn: psycopg.Connection, status: Optional[str] = None, limit: int = 50) -> list[dict]:
    query = "SELECT case_id, created_at, updated_at, status, recommendation, source_name FROM cases"
    params: list = []
    if status:
        query += " WHERE status = %s"
        params.append(status)
    query += " ORDER BY created_at DESC LIMIT %s"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    keys = ["case_id", "created_at", "updated_at", "status", "recommendation", "source_name"]
    return [dict(zip(keys, r)) for r in rows]
