# Latency and model choice (Week 6)

**Which model.** The default is now `claude-haiku-4-5` (`ANTHROPIC_MODEL`). Every measurement in this document and in the
case study was taken on `claude-sonnet-4-5`, before the switch, so the timings, cost and agreement figures below need
re-measuring on Haiku. Haiku is faster and about a third of the price per token, but the guardrails and prompts were
tuned against Sonnet and the effect on the answers is unmeasured: compare before trusting it (`baseline,all_sonnet`).

Baseline from the dashboard on real runs (Sonnet): a case takes about 70 s to reach the review pause (median), the slowest
1 in 20 about 81 s. The criteria step is 40 to 50 s of that. A reviewer waits for this once per case, so it is worth
cutting, but not at the cost of changing what the reviewer is told. Everything below is switchable and measured
before it becomes a default.

## Where the time goes

A step that calls a model spends almost all of its time **writing the answer**: reading a prompt of a few thousand
tokens takes a second or two, writing three or four thousand output tokens takes tens of seconds. The criteria step
writes the most (every pathway, every requirement, a quote and a rationale for each), so that is where the levers are.

The steps form a chain, and most of it cannot run side by side:

| Step | Needs | Why it cannot start earlier |
|---|---|---|
| intake | the note | first step |
| policy | the intake result (procedure, codes) | retrieval query is built from it; local and fast, so not worth overlapping |
| ehr | intake and the policy text | the chart agent decides what to look up from the policy's requirements; taking the policy away changes what it fetches, and Week 4 tuned exactly that |
| assess | note, policy and chart facts | it quotes chart facts |
| draft | the recommendation | the kind of document (submission, information request, memo) depends on it |

So the safe parallelism is inside the criteria step, not between steps.

## The levers

| Setting | What it does | Expected effect | Risk |
|---|---|---|---|
| `ASSESS_LEAN=true` | The model writes a shorter form: no repeated policy id and section on every requirement, no paraphrased `finding` next to each quote. Code expands it back to the full assessment, so every guardrail and `decide()` run unchanged. | Fewer output tokens. About a quarter fewer characters on the test fixture; the real figure is what the comparison measures. | A shorter schema might change how the model fills it in. |
| `ASSESS_SPLIT=true` | Two calls at once: pathways and exclusions, and general requirements. Wall time is the slower call. Tokens of both are added, and the input is sent twice. | Roughly the time of the larger half. | Two prompts to keep consistent; the summary now covers pathways and exclusions only, because the general requirements are written in the other call. A prerequisite section has to be listed by one of the two calls. |
| `INTAKE_MODEL`, `EHR_MODEL`, `ASSESS_MODEL`, `DRAFT_MODEL` | A different model per step. The steps that write little or do simple extraction can run on a smaller, faster model; the criteria step keeps the stronger one. | Lower time and cost on the steps moved. | Quality on that step. Intake feeds everything after it. |

All default to off / the main model. `ASSESS_SPLIT` implies the lean form.

Each trace event now records the model it ran on (and the assess event records `mode`: full, lean or split), so cost
and behaviour can be worked out from saved cases.

## Streaming progress

The API already exposes each step as it finishes. The case page now also shows a running clock on the active step,
so a 40 s step reads as "working, 23 s" instead of a frozen spinner. It does not make the case faster.

## How to measure

`scripts/compare_models.py` runs sample notes under several profiles up to the review pause (nothing is approved or
sent) and prints one table. From `backend\` with the venv active, database up, and a real key in `.env`:

```powershell
python ..\scripts\compare_models.py --profiles baseline,lean,split --notes note_03,note_06,note_02 --repeats 2 --out ..\eval\comparison.json
python ..\scripts\compare_models.py --profiles baseline,all_sonnet --notes note_03,note_06,note_02 --repeats 2   # Haiku against Sonnet
```

Presets: `baseline` (whatever `ANTHROPIC_MODEL` is, Haiku by default), `lean`, `split`, `sonnet_assess` (criteria step on
Sonnet, the rest on the default), `split_sonnet_assess`, `all_sonnet`. Custom: `"mix:intake=claude-haiku-4-5,assess=claude-sonnet-4-5,split=1"`. Each run is
real API usage of about 70 s. Prices in the script are list prices at the time of writing; check them, or pass
`--price MODEL=IN,OUT` (USD per million tokens). A model with no price shows n/a rather than a guess.

Columns: wall time (median and worst), assess step median, mean output tokens, mean cost, **same_recommendation** and
**same_pathways** (matches with the first profile on the same note), and mean guardrail notes per case.

### Reading the table

- The first profile is the reference. Its own row compares its repeats with its first run, which is the **noise
  floor**: if the same settings disagree with themselves 1 time in 6, a variant that disagrees 1 in 6 has not changed
  anything. This is why `--repeats 2` or more matters.
- **Adopt a setting only if** recommendation and pathway agreement are at the noise floor or better, and guardrail
  notes per case are not higher. More guardrail notes means the model is making more mistakes the code has to catch.
- A faster setting that changes a recommendation is not faster; it is a different product. Keep it off.
- Six sample notes are a smoke test, not a benchmark. Say so when quoting results.

## Results

Fill this in from your own run; nothing here is a result yet.

| profile | wall p50 | assess p50 | output tokens | cost / case | same recommendation | same pathways | guardrail notes |
|---|---|---|---|---|---|---|---|
| baseline | | | | | | | |
| lean | | | | | | | |
| split | | | | | | | |
| all_sonnet | | | | | | | |

Decision: (which settings became defaults, and the evidence).
