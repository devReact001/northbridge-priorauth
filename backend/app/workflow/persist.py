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


def load_case(conn: psycopg.Connection, case_id: str) -> Optional[dict]:
    """A saved case with its events, or None. Used when the live checkpointer no longer has the case."""
    row = conn.execute("SELECT state, status FROM cases WHERE case_id = %s", (case_id,)).fetchone()
    if row is None:
        return None
    events = conn.execute(
        """SELECT node, ts, latency_ms, input_tokens, output_tokens, detail
           FROM case_events WHERE case_id = %s ORDER BY seq""",
        (case_id,),
    ).fetchall()
    keys = ["node", "ts", "latency_ms", "input_tokens", "output_tokens", "detail"]
    trace = []
    for e in events:
        item = dict(zip(keys, e))
        item["ts"] = item["ts"].isoformat(timespec="seconds") if item["ts"] else None
        trace.append(item)
    state = dict(row[0])
    state["trace"] = trace
    return state


def load_for_metrics(conn: psycopg.Connection, days: int = 30) -> list[dict]:
    """Every case from the last `days` days, each with its trace events, for the dashboard."""
    cases = conn.execute(
        """SELECT case_id, created_at, status, recommendation, state
           FROM cases WHERE created_at >= now() - make_interval(days => %s) ORDER BY created_at""",
        (days,),
    ).fetchall()
    events = conn.execute(
        """SELECT e.case_id, e.node, e.latency_ms, e.input_tokens, e.output_tokens, e.detail
           FROM case_events e JOIN cases c ON c.case_id = e.case_id
           WHERE c.created_at >= now() - make_interval(days => %s) ORDER BY e.case_id, e.seq""",
        (days,),
    ).fetchall()
    by_case: dict[str, list[dict]] = {}
    for case_id, node, latency, tin, tout, detail in events:
        by_case.setdefault(case_id, []).append(
            {"node": node, "latency_ms": latency, "input_tokens": tin, "output_tokens": tout, "detail": detail or {}}
        )
    return [
        {"case_id": cid, "created_at": created, "status": status, "recommendation": rec,
         "state": state, "events": by_case.get(cid, [])}
        for cid, created, status, rec, state in cases
    ]
