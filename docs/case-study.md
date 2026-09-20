# Case study: a prior authorization copilot that a reviewer can trust

*Portfolio project by Prasad Deepak. A fictional client (Northbridge Health, a regional hospital network), a fictional
payer, and synthetic data only. The client's baselines in the discovery document are assumptions, so this case study
makes no claim about hours saved. Numbers below are from my own runs and are labelled with how many runs they rest on.*

## The problem

Before a scan can be scheduled, the payer wants proof the patient meets its coverage criteria. Staff read the
clinical note, find the payer's policy in a long PDF, check each criterion by hand, and write the request. It is slow,
and the expensive failures are avoidable ones: a denial because a note never mentioned conservative therapy that the
chart does record.

The brief I set myself was narrow on purpose: give the reviewer a pre-filled, evidence-cited case file, and never
make the coverage decision. That constraint shaped everything else.

## What I built

A pipeline of small steps, run as a LangGraph state machine and reviewed by a person at the end of every case:

1. **Intake** reads the clinical note into structured facts. Every fact carries a verbatim quote, and code checks
   each quote against the note.
2. **Policy** picks the right payer policy with hybrid retrieval (vector and keyword, then a cross-encoder rerank).
3. **Chart lookup** lets a model choose which read-only tools to call on a FHIR server (through MCP) to find what the
   note leaves out, such as the radiograph, therapy dates and prior scans. The text of every chart fact is produced
   by code from the FHIR record, so the model cannot reword or invent one.
4. **Criteria** checks the note and chart facts against the whole policy, requirement by requirement, with quotes.
5. **Draft** writes a submission letter, an information request, or an internal risk memo, depending on the result.
6. **Human review.** The graph pauses. The reviewer approves, edits or rejects. Only then does anything go out, and
   what goes out (a FHIR Claim, or a message to the clinician) is chosen by code from the document type.

A Next.js app shows the queue, the review page (evidence with highlighted quotes, chart facts, guardrail notes, an
editable draft) and a dashboard of outcomes, reviewer actions, latency per step, safeguards that fired and send-out
health. It runs on Kubernetes with the models baked into the image, health and readiness probes, non-root
containers and network policies.

## Decisions that mattered

**The model reads; code decides.** The recommendation (`likely_meets`, `needs_more_info`, `likely_not_meets`) is
computed by a plain function from the model's findings. Routing is plain code. So is the choice of what to send.
Everything that has a consequence is deterministic, unit-tested and explainable to a reviewer or an auditor.

**Guardrails sit between the model and the decision.** A "met" requirement with no verifiable quote is downgraded to
"unclear". A quote is checked against one source at a time, so a quote stitched together from the note and the chart
never verifies. An exclusion phrased as an absence ("no exam documented") is forced to a documentation gap. A
"not met" with no affirmative evidence becomes "unclear". Each guardrail exists because a real run went wrong, and
each one leaves a note the reviewer can read.

**Missing documentation is never evidence against the patient.** The system says "unclear" and asks for the
information, because the information often exists somewhere else. That is why chart lookup exists.

**The reviewer's decision is protected too.** A draft with `[placeholders]` cannot be approved, and the API enforces
it, not just the button. The document that goes out is always the text a human saw.

## What broke, and what it taught me

Real runs against the model found more than the tests did, and I fixed them in that order:

- A policy section that is a *prerequisite* (a required radiograph) was being treated as an approval pathway. Because
  one pathway met is enough, that section made a note falsely look like it qualified. The fix was to have code move
  prerequisite requirements out of the pathway list, and the lesson was to look at the wrong answers, not only the
  right ones.
- Long answers were being cut off at the token limit, which surfaced as "no pathways found". The fix was to detect
  truncation explicitly, raise the limit, and retry once with the reason recorded.
- A model that writes "exam limited" and calls it a documented exclusion. The fix was a rule in code that
  absence-worded exclusions are documentation gaps.

None of these was visible in a unit test written before I saw the model's behaviour. The suite now has 162 backend and
10 frontend tests, but they are regression protection for those runs, not proof that the model is right.

## Results so far

These runs used Claude Sonnet 4.5. The default model is now Claude Haiku 4.5, which is faster and cheaper but has not been
measured against Sonnet on these notes yet, so every figure below should be re-run before it is quoted.

- **Retrieval:** on a 38-question eval I wrote myself after seeing the baseline's weaknesses, the reranked hybrid
  reached hit@1 of 87% (vector alone 76%) and MRR 0.890. The eval is small and I designed it, so read it as
  directional. Details and the experiments that did not work are in [retrieval-experiments.md](retrieval-experiments.md).
- **Speed:** the median case took about 70 s to reach the review pause (slowest 1 in 20 about 81 s, 29 real runs);
  the criteria step was about 41 s of that. It is the model writing thousands of tokens, not reading.
- **A faster variant, preliminary:** splitting the criteria step into two parallel calls (pathways and general
  requirements) took the criteria step from 41.6 s to 20.3 s and the whole case from about 66 s to 45 s, at about 10%
  more cost (about $0.13 to $0.15 per case). The recommendation matched the baseline in 4 of 4 runs and pathway
  statuses in 3 of 4. That is 8 runs, and one difference is not yet explained, so it stays off by default until a larger
  comparison shows it is within the run-to-run noise. The comparison tool prints that noise floor next to every
  difference so the result cannot be over-read: [latency-and-models.md](latency-and-models.md).

## What I would do next

- **A work queue and a worker.** A case runs in a background thread of the API pod that accepted it, so a restart
  loses it and the API cannot run more than one replica. A queue with separate workers fixes both.
- **Real authentication** for reviewers, so the recorded reviewer name is a fact and not something typed.
- **A larger, independently written eval** of extraction and criteria, not only retrieval, run on every change.
- **Alerting** on the signals the dashboard already computes: changed-answer rate, safeguards firing, latency.
- **A production deployment shape:** TLS and an Ingress, a registry, secrets from a manager, replicated Postgres with a
  tested restore, and a cluster whose network plugin enforces the policies.

## How to describe it in an interview

I built an assistive system where the model does the reading and code does the deciding, with a human at the end of
every case. The interesting work was not the prompt, it was the guardrails between the model and the decision, found by
running real notes and looking at the wrong answers. I measured latency before changing it, made each speed-up a
switch, and built a tool that reports whether a faster setting changes the answers, including how much the answers
move with nothing changed. It is deployed on Kubernetes with the limitations written down in a runbook.
