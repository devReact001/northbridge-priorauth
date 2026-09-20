# Northbridge Prior Authorization Copilot

A multi-agent assistant that helps hospital utilization-review staff prepare prior authorization cases. It extracts evidence from clinical notes, checks it against payer policy, and drafts a submission, with a human reviewer approving every case.

> **Synthetic data only.** This is a portfolio project. It assists reviewers and is not a clinical or coverage decision system. The payer ("Meridian Health Plan") and its policies are fictional.

Status: **Week 2 of 6** (RAG over payer policies with a scored eval set). See [docs/discovery.md](docs/discovery.md) for the client engagement.

## Setup (Windows PowerShell)

```powershell
copy .env.example .env                 # then add your ANTHROPIC_API_KEY
docker compose up -d db                # Postgres + pgvector

cd backend
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt -r requirements-rag.txt
pytest                                 # no API key or model download needed
```

macOS / Linux: same steps, with `cp` instead of `copy` and `source .venv/bin/activate`.

## Week 1: intake agent

```powershell
python ..\scripts\run_intake.py app\data\sample_notes\note_01_mri_lumbar.txt   # complete note
python ..\scripts\run_intake.py app\data\sample_notes\note_02_incomplete.txt   # flags missing info
```

- Claude tool-use with a forced tool call, so output always matches the `IntakeResult` schema.
- Every clinical fact carries a verbatim quote, and each quote is checked against the note (`unverified_quotes`).
- Missing information is listed, never guessed. Low confidence, gaps or unverified quotes set `needs_human_review`.

## Week 2: policy RAG

Four fictional payer policy PDFs live in `policies/pdf/` (sources in `policies/src/`). Retrieval is section-level, hybrid (vector + keyword, merged with Reciprocal Rank Fusion), and every hit carries policy id, section and page for citation. Embeddings come from a local model (`BAAI/bge-small-en-v1.5`) so documents never leave the machine; the `Embedder` interface makes it possible to compare hosted models later.

```powershell
python -m app.rag.ingest --reset                 # chunk PDFs, embed, store (first run downloads the model)
python ..\scripts\eval_retrieval.py --show-misses  # score keyword vs vector vs hybrid
uvicorn app.main:app --reload                    # try GET /policy/search?q=... at http://localhost:8000/docs
```

Scores are written to `eval/results.md`. Re-run the eval after every change to chunking or retrieval, and record what moved.

## Roadmap

| Week | Deliverable |
|---|---|
| 1 | Discovery doc, scaffold, intake agent (done) |
| 2 | RAG over payer policies, eval set and baseline score |
| 3 | LangGraph multi-agent workflow with human approval |
| 4 | FHIR MCP server and integrations |
| 5 | Next.js reviewer and observability dashboard |
| 6 | Kubernetes deployment, runbook, model comparison, case study |

## Project layout

```
backend/app/agents/   intake agent
backend/app/rag/      chunking, embedder interface, pgvector store, hybrid search, metrics
backend/tests/        pytest (fake Claude client, no database needed)
policies/             fictional payer policies (markdown source + generated PDFs)
eval/                 30-question retrieval eval set and latest results
db/init.sql           Postgres schema (pgvector enabled)
docs/discovery.md     client discovery document
scripts/              CLI helpers (run_intake, make_policy_pdfs, eval_retrieval)
```
