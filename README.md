# Northbridge Prior Authorization Copilot

A multi-agent assistant that helps hospital utilization-review staff prepare prior authorization cases. It extracts evidence from clinical notes, checks it against payer policy, and drafts a submission, with a human reviewer approving every case.

> **Synthetic data only.** This is a portfolio project. It assists reviewers and is not a clinical or coverage decision system. The payer ("Meridian Health Plan") and its policies are fictional.

Status: **Week 6 of 6** (deployment, runbook, latency and model comparison, case study). Docs: [discovery](docs/discovery.md), [architecture](docs/architecture.md), [integrations](docs/integrations.md), [retrieval experiments](docs/retrieval-experiments.md), [latency and models](docs/latency-and-models.md), [deployment](docs/deployment.md), [runbook](docs/runbook.md), [case study](docs/case-study.md).

## Setup (Windows PowerShell)

```powershell
copy .env.example .env                 # then add your ANTHROPIC_API_KEY
docker compose up -d db                # Postgres + pgvector

cd backend
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt -r requirements-rag.txt
pytest                                 # no API key, database or model download needed (starts two small MCP servers)
python -m app.rag.ingest --reset       # load the policy PDFs (first run downloads the embedding model)
```

macOS / Linux: same steps, with `cp` instead of `copy` and `source .venv/bin/activate`.

## Run a case end to end

```powershell
python ..\scripts\run_workflow.py app\data\sample_notes\note_03_knee_meets.txt --request-date 2026-03-20
```

The terminal shows the chart lookup (which MCP tools were called and the facts they returned), the review packet
(recommendation, each policy requirement with its evidence quote and where the quote came from, a draft) and asks you
to approve, edit or reject. After you approve, it shows what was sent out. Each note takes a different route. The
sample notes are dated in March and April 2026, so pass a `--request-date` close to the visit date:

| Note | Request date | Expected route |
|---|---|---|
| `note_03_knee_meets.txt` | 2026-03-20 | criteria met, chart corroborates, submission letter |
| `note_01_mri_lumbar.txt` | 2026-03-20 | criteria met, submission letter |
| `note_02_incomplete.txt` | 2026-04-05 | thin note; the chart supplies the radiograph, therapy, exam and codes; one gap (locking or catching) remains, so an information request for that alone |
| `note_06_knee_repeat_mri.txt` | 2026-03-20 | note looks complete, but the chart shows an MRI of the same knee two months earlier: a human must decide |
| `note_04_lumbar_acute.txt` | 2026-03-25 | exclusion applies, denial-risk memo (internal, nothing sent) |
| `note_05_chest_ct.txt` | 2026-03-30 | no policy covers a chest CT, escalated to a human without a draft |

Approving a submission letter writes a FHIR `Claim` to the `outbox` folder; approving an information request writes a
message there; rejecting, or approving a memo, sends nothing. Set `EHR_ENABLED=false` in `.env` to run the note-only
workflow and compare.

Or use the API (`uvicorn app.main:app --reload`, then open http://localhost:8000/docs):

```powershell
$note = Get-Content app\data\sample_notes\note_03_knee_meets.txt -Raw
$case = Invoke-RestMethod -Method Post -Uri http://localhost:8000/cases -ContentType "application/json" -Body (@{text=$note} | ConvertTo-Json)
$case.status; $case.recommendation
Invoke-RestMethod -Method Post -Uri "http://localhost:8000/cases/$($case.case_id)/review" -ContentType "application/json" -Body (@{action="approve"; reviewer="Nurse Rao"} | ConvertTo-Json)
```

Set `CHECKPOINTER=postgres` in `.env` to keep paused cases across API restarts. Set `API_KEY` to require an `X-API-Key` header.

## Reviewer UI and dashboard

Needs Node 18.18+ (20 recommended). Two terminals:

```powershell
# terminal 1: the API (from backend\, venv active)
uvicorn app.main:app --reload

# terminal 2: the UI
cd frontend
copy .env.example .env.local           # API_BASE_URL=http://localhost:8000, API_KEY only if you set one
npm install
npm run dev                            # http://localhost:3000
```

Pick a sample on **New case**, watch it work, then approve, edit or reject on the case page. **Dashboard** shows
outcomes, reviewer actions, latency per step, guardrail activity, chart lookup and dispatch health. Use
`CHECKPOINTER=postgres` so a case waiting for review survives an API restart.

No key or database handy? `python ..\scripts\demo_api.py` (from `backend\`) serves the same API on a scripted fake
model with synthetic dashboard data.

## Speed and model choice

The criteria step is 40 to 50 s of a 70 s case. `ASSESS_LEAN`, `ASSESS_SPLIT` and a model per step (`INTAKE_MODEL`,
`EHR_MODEL`, `ASSESS_MODEL`, `DRAFT_MODEL`) are all off by default. `scripts/compare_models.py` runs the sample notes
under several settings and reports time, tokens, cost, and whether the recommendation changed. Method and how to read
the table: [docs/latency-and-models.md](docs/latency-and-models.md).

## Run it on Kubernetes

Docker Desktop with Kubernetes enabled, then:

```powershell
.\scripts\k8s-deploy.ps1        # builds two images, creates secrets, deploys, loads the policies
# open http://localhost:8080
.\scripts\k8s-down.ps1 -Stop    # stop, keep the data;  .\scripts\k8s-down.ps1 deletes everything
```

Details, what it is and is not: [docs/deployment.md](docs/deployment.md). When something is wrong:
[docs/runbook.md](docs/runbook.md). CI (`.github/workflows/ci.yml`) runs the tests, builds the UI, validates the
manifests and builds both images.

## Earlier weeks

- **Week 1, intake agent:** Claude tool-use with a forced tool call, verbatim quote for every fact, quotes verified against the note, missing information listed instead of guessed. `python ..\scripts\run_intake.py <note>`
- **Week 2, policy RAG:** section-level chunking of four fictional payer policy PDFs, vector / keyword / hybrid search, a 38-question eval set and a log of retrieval experiments. `python ..\scripts\eval_retrieval.py --modes all --show-misses`

## Roadmap

| Week | Deliverable |
|---|---|
| 1 | Discovery doc, scaffold, intake agent (done) |
| 2 | RAG over payer policies, eval set and baseline score (done) |
| 3 | LangGraph multi-agent workflow with human approval (done) |
| 4 | FHIR MCP server and integrations (done) |
| 5 | Next.js reviewer and observability dashboard (done) |
| 6 | Kubernetes deployment, runbook, model comparison, case study (done) |

## Project layout

```
backend/app/agents/     intake, ehr, criteria, drafter agents and the LLM helper
backend/app/fhir/       FHIR sources (files or REST), fact builder, the read-only tool surface
backend/app/mcp_servers/ FHIR (read) and outbound (write) MCP servers
backend/app/mcp_client.py  synchronous MCP client used by the workflow
backend/app/workflow/   LangGraph graph, state, persistence, runtime wiring
backend/app/rag/        chunking, embedder interface, pgvector store, search strategies, reranker, metrics
frontend/               Next.js reviewer UI and dashboard (proxy route keeps the API key server-side)
k8s/                    Kubernetes manifests (Postgres, API, web, network policies, ingest Job)
backend/tests/          pytest with fake Claude, real policy PDFs, in-memory checkpointer
policies/               fictional payer policies (markdown source + generated PDFs)
eval/                   38-question retrieval eval set and latest results
db/init.sql             Postgres schema
docs/                   discovery, architecture, integrations, retrieval experiments, latency, deployment, runbook, case study
scripts/                run_intake, run_workflow, demo_api, compare_models, make_policy_pdfs, make_fhir_fixtures, eval_retrieval
```
