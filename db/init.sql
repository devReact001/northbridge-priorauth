CREATE EXTENSION IF NOT EXISTS vector;

-- Every intake run is stored so the Week 5 dashboard has data to trace.
CREATE TABLE IF NOT EXISTS intake_runs (
    id            SERIAL PRIMARY KEY,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_name   TEXT,
    raw_text      TEXT NOT NULL,
    result        JSONB NOT NULL,
    model         TEXT,
    latency_ms    INTEGER,
    input_tokens  INTEGER,
    output_tokens INTEGER
);

-- Policy chunks for RAG. `python -m app.rag.ingest --reset` drops and recreates this table
-- with the dimension of the chosen embedder (384 for the local BGE model), so this
-- definition only matters for a fresh database.
CREATE TABLE IF NOT EXISTS policy_chunks (
    id           SERIAL PRIMARY KEY,
    policy_id    TEXT NOT NULL,
    policy_title TEXT,
    section      TEXT NOT NULL,
    heading      TEXT,
    page         INTEGER,
    content      TEXT NOT NULL,
    embedder     TEXT,
    embedding    vector(384) NOT NULL,
    content_tsv  tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
);
CREATE INDEX IF NOT EXISTS policy_chunks_tsv_idx ON policy_chunks USING gin (content_tsv);
CREATE INDEX IF NOT EXISTS policy_chunks_vec_idx ON policy_chunks USING hnsw (embedding vector_cosine_ops);

-- Week 3: one row per case plus one row per workflow step (the trace the Week 5 dashboard reads).
-- The API also creates these tables on first use, so an existing database needs no migration.
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
