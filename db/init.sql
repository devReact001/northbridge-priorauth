CREATE EXTENSION IF NOT EXISTS vector;

-- Week 1: store every intake run so Week 5's dashboard has data to trace.
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

-- Week 2: policy chunks for RAG (embedding dimension is set when you choose a model).
CREATE TABLE IF NOT EXISTS policy_chunks (
    id         SERIAL PRIMARY KEY,
    policy_id  TEXT NOT NULL,
    section    TEXT,
    content    TEXT NOT NULL,
    embedding  vector(1024)
);
