# Discovery Document: Prior Authorization Copilot for Northbridge Health

*Fictional client engagement. Synthetic data only. Author: Prasad Deepak. Status: Week 1 draft.*

## 1. Client background

Northbridge Health is a fictional 400-bed regional hospital network with outpatient imaging and orthopedic clinics. Its utilization-review team handles roughly 1,200 prior authorization (PA) requests per week across several payers.

## 2. The problem

Clinicians order a procedure (for example, a lumbar MRI). Before it can be scheduled, the payer requires proof that the patient meets its coverage criteria. Today, staff read the clinical note, find the matching payer policy, check each criterion by hand, and write the submission. Typical pain points reported by the review team:

- Average of 25 to 40 minutes of staff time per request.
- Frequent denials caused by missing documentation (for example, no record of conservative therapy) that could have been caught before submission.
- Payer policies change often and live in long PDFs.
- Staff work across the EHR, PDFs, email, and payer portals.

## 3. Goal

Reduce staff time per request and cut avoidable denials by giving reviewers a pre-filled, evidence-cited case file. **The system assists reviewers. It never makes the final coverage or clinical decision.**

## 4. Success metrics (proposed, to be validated with the client)

| Metric | Baseline (assumed) | Target |
|---|---|---|
| Staff time per request | 30 min | under 10 min |
| Denials from missing documentation | 18% | under 8% |
| Criterion-level extraction accuracy (our eval set) | n/a | 90% or higher |
| Policy retrieval accuracy (top-3 contains the right clause) | n/a | 90% or higher |
| Cases sent to a human when confidence is low or info is missing | n/a | 100% |

Baselines are assumptions for this fictional engagement and should be labelled as such in the README.

## 5. Scope

**In scope (MVP):** imaging PA requests (MRI and CT) for musculoskeletal conditions; ingesting clinical notes and referral PDFs; retrieving relevant payer policy clauses; checking evidence against criteria; drafting a submission or appeal letter; reviewer approval queue; audit trail.

**Out of scope:** submitting directly to payer portals; any final approve/deny decision; real patient data; billing and claims adjudication.

## 6. Users

- **Utilization-review nurse (primary):** reviews the case file, approves or edits, sends.
- **Ordering clinician (secondary):** sees what documentation is missing.
- **Operations lead:** watches throughput, failures, cost, and quality on a dashboard.

## 7. Systems and integrations

- EHR data through a FHIR R4 API (Patient, Condition, Procedure, DocumentReference).
- Payer policy documents (PDF).
- Notifications through Slack or email.

## 8. Constraints and risks

| Risk | Mitigation |
|---|---|
| Privacy (HIPAA) | Synthetic data only in this project; in a real deployment: BAA with the model provider, PHI minimization, encryption, access controls, audit log |
| Hallucinated clinical facts | Extraction restricted to what the note states; every fact carries a verbatim quote; missing info is listed, never guessed |
| Over-reliance on the AI | Human approval required; low confidence or missing info always routes to a reviewer |
| Policy drift | Versioned policy documents; re-index on change; eval set re-run on every change |
| Vendor or model change | Model name configurable; eval set detects regressions |

## 9. Architecture (target, built across 6 weeks)

Supervisor agent (LangGraph) delegating to intake, policy (RAG), criteria-matching, and drafting agents; FHIR access via an MCP server; FastAPI backend; Postgres with pgvector; Next.js reviewer and observability dashboard; Docker and Kubernetes deployment.

## 10. Open questions for the client

1. Which payers and policies are highest volume?
2. What does the EHR expose today (FHIR version, auth method)?
3. Who signs off on the letter template?
4. What is the acceptable turnaround time per request?
5. Is there an existing audit or retention policy we must follow?

## 11. Milestones

Week 1 discovery and intake agent; Week 2 RAG and eval; Week 3 multi-agent graph and approval step; Week 4 FHIR and MCP integrations; Week 5 dashboard; Week 6 deployment, runbook, and case study.
