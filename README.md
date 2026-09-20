# Northbridge Prior Authorization Copilot

A multi-agent assistant that helps hospital utilization-review staff prepare prior authorization cases. It extracts evidence from clinical notes, checks it against payer policy, and drafts a submission, with a human reviewer approving every case.

> **Synthetic data only.** This is a portfolio project. It assists reviewers and is not a clinical or coverage decision system.

Status: **Week 1 of 6** (discovery doc, scaffold, intake agent). See [docs/discovery.md](docs/discovery.md).

## Quick start

```bash
cp .env.example .env            # add your ANTHROPIC_API_KEY
docker compose up -d db         # Postgres + pgvector

cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest                          # runs with a fake client, no API key needed
uvicorn app.main:app --reload   # http://localhost:8000/docs
```

Try the intake agent on a sample note:

```bash
python ../scripts/run_intake.py app/data/sample_notes/note_01_mri_lumbar.txt   # complete note
python ../scripts/run_intake.py app/data/sample_notes/note_02_incomplete.txt   # should flag missing info
```

## What the intake agent does

- Uses Claude tool-use with a forced tool call, so output always matches the `IntakeResult` schema.
- Every clinical fact carries a verbatim quote from the note.
- Missing information is listed, never guessed.
- `needs_human_review` is true when confidence is under 0.75 or anything is missing.
- Every run is saved to Postgres (tokens, latency, result) to feed the Week 5 dashboard.

## Roadmap

| Week | Deliverable |
|---|---|
| 1 | Discovery doc, scaffold, intake agent |
| 2 | RAG over payer policies, eval set and baseline score |
| 3 | LangGraph multi-agent workflow with human approval |
| 4 | FHIR MCP server and integrations |
| 5 | Next.js reviewer and observability dashboard |
| 6 | Kubernetes deployment, runbook, case study |

## Project layout

```
backend/app/        FastAPI app, agents, schemas
backend/tests/      pytest (fake Claude client)
db/init.sql         Postgres schema (pgvector enabled)
docs/discovery.md   Client discovery document
scripts/            CLI helpers and Synthea setup notes
```
