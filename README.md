# Northbridge Prior Authorization Copilot

A multi-agent assistant that helps hospital utilization-review staff prepare prior authorization cases. It extracts evidence from clinical notes, checks it against payer policy, and drafts a submission, with a human reviewer approving every case.

> **Synthetic data only.** This is a portfolio project. It assists reviewers and is not a clinical or coverage decision system. The payer ("Meridian Health Plan") and its policies are fictional.

Status: **Week 3 of 6** (multi-agent workflow with human approval). Docs: [discovery](docs/discovery.md), [architecture](docs/architecture.md), [retrieval experiments](docs/retrieval-experiments.md).

## Setup (Windows PowerShell)

```powershell
copy .env.example .env                 # then add your ANTHROPIC_API_KEY
docker compose up -d db                # Postgres + pgvector

cd backend
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt -r requirements-rag.txt
pytest                                 # no API key, database or model download needed
python -m app.rag.ingest --reset       # load the policy PDFs (first run downloads the embedding model)
```

macOS / Linux: same steps, with `cp` instead of `copy` and `source .venv/bin/activate`.

## Week 3: run a case end to end

```powershell
python ..\scripts\run_workflow.py app\data\sample_notes\note_03_knee_meets.txt
```

The terminal shows the review packet (recommendation, each policy requirement with its evidence quote, a draft) and asks you to approve, edit or reject. Try all of the sample notes, because each takes a different route:

| Note | Expected route |
|---|---|
| `note_03_knee_meets.txt` | criteria met, submission letter |
| `note_02_incomplete.txt` | missing information, request to the clinician |
| `note_04_lumbar_acute.txt` | exclusion applies, denial-risk memo |
| `note_05_chest_ct.txt` | no policy covers a chest CT, escalated to a human without a draft |

Or use the API (`uvicorn app.main:app --reload`, then open http://localhost:8000/docs):

```powershell
$note = Get-Content app\data\sample_notes\note_03_knee_meets.txt -Raw
$case = Invoke-RestMethod -Method Post -Uri http://localhost:8000/cases -ContentType "application/json" -Body (@{text=$note} | ConvertTo-Json)
$case.status; $case.recommendation
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/cases/$($case.case_id)/review" -ContentType "application/json" -Body (@{action="approve"; reviewer="Nurse Rao"} | ConvertTo-Json)
```

Set `CHECKPOINTER=postgres` in `.env` to keep paused cases across API restarts.

## Earlier weeks

- **Week 1, intake agent:** Claude tool-use with a forced tool call, verbatim quote for every fact, quotes verified against the note, missing information listed instead of guessed. `python ..\scripts\run_intake.py <note>`
- **Week 2, policy RAG:** section-level chunking of four fictional payer policy PDFs, vector / keyword / hybrid search, a 38-question eval set and a log of retrieval experiments. `python ..\scripts\eval_retrieval.py --modes all --show-misses`

## Roadmap

| Week | Deliverable |
|---|---|
| 1 | Discovery doc, scaffold, intake agent (done) |
| 2 | RAG over payer policies, eval set and baseline score (done) |
| 3 | LangGraph multi-agent workflow with human approval (done) |
| 4 | FHIR MCP server and integrations |
| 5 | Next.js reviewer and observability dashboard |
| 6 | Kubernetes deployment, runbook, model comparison, case study |

## Project layout

```
backend/app/agents/     intake, criteria, drafter agents and the LLM helper
backend/app/workflow/   LangGraph graph, state, persistence, runtime wiring
backend/app/rag/        chunking, embedder interface, pgvector store, search strategies, reranker, metrics
backend/tests/          pytest with fake Claude, real policy PDFs, in-memory checkpointer
policies/               fictional payer policies (markdown source + generated PDFs)
eval/                   38-question retrieval eval set and latest results
db/init.sql             Postgres schema
docs/                   discovery, architecture, retrieval experiments
scripts/                run_intake, run_workflow, make_policy_pdfs, eval_retrieval
```
