"""Postgres + pgvector storage and the two raw search primitives (vector, keyword)."""

import re
from typing import Sequence

import psycopg

from ..config import settings


def connect() -> psycopg.Connection:
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg.connect(settings.database_url)


def vec_literal(vec: Sequence[float]) -> str:
    """pgvector accepts '[0.1,0.2,...]' text, so we do not need an extra Python package."""
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


def reset_schema(conn: psycopg.Connection, dim: int) -> None:
    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    conn.execute("DROP TABLE IF EXISTS policy_chunks")
    conn.execute(
        f"""
        CREATE TABLE policy_chunks (
            id           SERIAL PRIMARY KEY,
            policy_id    TEXT NOT NULL,
            policy_title TEXT,
            section      TEXT NOT NULL,
            heading      TEXT,
            page         INTEGER,
            content      TEXT NOT NULL,
            embedder     TEXT,
            embedding    vector({int(dim)}) NOT NULL,
            content_tsv  tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
        )
        """
    )
    conn.execute("CREATE INDEX policy_chunks_tsv_idx ON policy_chunks USING gin (content_tsv)")
    conn.execute("CREATE INDEX policy_chunks_vec_idx ON policy_chunks USING hnsw (embedding vector_cosine_ops)")


def insert_chunks(conn: psycopg.Connection, chunks, vectors, embedder_name: str) -> None:
    with conn.cursor() as cur:
        for c, v in zip(chunks, vectors):
            cur.execute(
                """INSERT INTO policy_chunks
                   (policy_id, policy_title, section, heading, page, content, embedder, embedding)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s::vector)""",
                (c.policy_id, c.policy_title, c.section, c.heading, c.page, c.text, embedder_name, vec_literal(v)),
            )


_COLS = "id, policy_id, section, heading, page, content"


def vector_search(conn: psycopg.Connection, query_vec: Sequence[float], k: int = 20) -> list[dict]:
    rows = conn.execute(
        f"""SELECT {_COLS}, 1 - (embedding <=> %s::vector) AS score
            FROM policy_chunks ORDER BY embedding <=> %s::vector LIMIT %s""",
        (vec_literal(query_vec), vec_literal(query_vec), k),
    ).fetchall()
    return [_row(r) for r in rows]


def build_or_tsquery(query: str) -> str:
    """Natural-language questions contain many words; require ANY of them (OR), rank by overlap."""
    tokens = re.findall(r"[a-zA-Z0-9]+", query.lower())
    return " | ".join(dict.fromkeys(tokens))


def keyword_search(conn: psycopg.Connection, query: str, k: int = 20) -> list[dict]:
    tsq = build_or_tsquery(query)
    if not tsq:
        return []
    rows = conn.execute(
        f"""SELECT {_COLS}, ts_rank_cd(content_tsv, q) AS score
            FROM policy_chunks, to_tsquery('english', %s) q
            WHERE content_tsv @@ q ORDER BY score DESC LIMIT %s""",
        (tsq, k),
    ).fetchall()
    return [_row(r) for r in rows]


def _row(r) -> dict:
    return {
        "id": r[0], "policy_id": r[1], "section": r[2], "heading": r[3],
        "page": r[4], "content": r[5], "score": float(r[6]),
    }
