# Retrieval experiments log

Rule: change one thing, re-run `python ..\scripts\eval_retrieval.py --modes all`, record the result here, keep or revert.

## Baseline (Week 2, 30 semantic questions, embedder BAAI/bge-small-en-v1.5)

| mode | hit@1 | hit@3 | hit@5 | MRR |
|---|---|---|---|---|
| keyword | 53% | 73% | 83% | 0.653 |
| vector | 90% | 97% | 100% | 0.934 |
| hybrid | 67% | 87% | 100% | 0.791 |

**Finding:** hybrid search scored below vector search alone. The keyword retriever ORs every word in a
natural-language question, including "how", "long" and "have", so its ranking is mostly noise, and equal-weight
Reciprocal Rank Fusion lets that noise pull down a strong vector ranking. The question set was also almost
entirely paraphrased questions, which favor embeddings.

## Experiments (Week 3, 38 questions: 30 semantic, 8 exact-identifier)

| # | Change | Hypothesis | Result | Decision |
|---|---|---|---|---|
| 1 | `keyword_clean`: drop question words and domain-ubiquitous words from the keyword query | Keyword search improves because it matches on clinical terms and codes | Worse. Overall MRR 0.693 vs 0.726 for plain keyword; semantic MRR 0.611 vs 0.653; exact questions unchanged at 100%. | Rejected. The stoplist removed useful signal. Code kept, not used. |
| 2 | `hybrid_clean`: hybrid with the cleaned keyword query | Fusion recovers most of the loss from the noisy keyword ranking | Mixed. hit@3 up (89% vs 87%) but hit@1 (61% vs 63%), hit@5 (95% vs 100%) and MRR (0.747 vs 0.766) down. | Rejected. |
| 3 | `hybrid_w3`: vector weighted 3x in fusion | A stronger retriever should count for more | Helps hybrid: overall MRR 0.793 vs 0.766, semantic MRR 0.862 vs 0.791. Still below vector alone (0.835 overall, 0.934 semantic), and worse than plain hybrid on exact questions (MRR 0.535 vs 0.671). | Partial. Kept as the fusion step in front of the reranker. |
| 4 | 8 exact-identifier questions (CPT codes, named tests) added | Keyword-style matching beats vector on exact terms even if it loses on paraphrases | Confirmed. On exact questions keyword gets 100% hit@1 and vector only 25% (MRR 0.463). On CPT-code questions q31, q37 and q38 vector's top 3 did not contain the right policy at all. | Confirmed. Exact identifiers are the reason to keep a keyword signal. |
| 5 | `vector_rerank`, `hybrid_w3_rerank`: cross-encoder reranks the top 20 | Reranking separates near-duplicate sibling sections (for example 3.2 vs 3.3) | Best overall: hit@1 87%, MRR 0.890 (vector 76%, 0.835). Exact hit@1 rises from 25% to 88%. Costs a little on semantic questions (MRR 0.894 vs 0.934) and hit@5 falls from 97% to 92%. The two rerank modes score identically. | Adopted for the workflow, see below. |

### Full results (38 questions)

| mode | hit@1 | hit@3 | hit@5 | MRR |
|---|---|---|---|---|
| keyword | 63% | 79% | 87% | 0.726 |
| keyword_clean | 61% | 82% | 82% | 0.693 |
| vector | 76% | 87% | 97% | 0.835 |
| hybrid | 63% | 87% | 100% | 0.766 |
| hybrid_clean | 61% | 89% | 95% | 0.747 |
| hybrid_w3 | 71% | 87% | 95% | 0.793 |
| vector_rerank | 87% | 92% | 92% | 0.890 |
| hybrid_w3_rerank | 87% | 92% | 92% | 0.890 |

Exact questions (n=8), MRR: keyword 1.000, keyword_clean 1.000, vector 0.463, hybrid 0.671, hybrid_clean 0.671,
hybrid_w3 0.535, vector_rerank 0.875, hybrid_w3_rerank 0.875.

Semantic questions (n=30), MRR: keyword 0.653, keyword_clean 0.611, vector 0.934, hybrid 0.791, hybrid_clean 0.768,
hybrid_w3 0.862, vector_rerank 0.894, hybrid_w3_rerank 0.894.

## Decision

The workflow default is `hybrid_w3_rerank`.

- It ties `vector_rerank` on this eval, so the eval cannot separate them. It is chosen because it also runs keyword
  search, which protects exact identifiers (CPT codes, named tests, member IDs) that real requests contain and
  where vector search alone was weakest.
- The cost is a second model (about 90 MB) and extra latency per case. Latency of the rerank step has not been
  measured yet. If it matters for a demo, `vector_rerank` is the fallback: set `RETRIEVAL_MODE=vector_rerank` in `.env`.

## Questions every mode misses

`q02` (urinary retention and groin numbness, expected 3.1), `q11` (knee giving way, expected 3.3) and `q35`
(empty can Jobe test, expected section 2) miss the top 3 in almost every mode. When every method fails the same
question, suspect the label or the policy wording before adding retrieval machinery. To do: read those three
sections in `policies/src` and decide whether the expected answer is the only right one.

## Caveats

- 38 questions is small: one question is worth about 2.6 points overall and 12.5 points on the exact subset.
- The policies and the questions were written by the same person, and the exact-identifier questions were added
  after seeing the baseline weaknesses. Treat the rankings as directional.
- A rerank model trained on web search (the default here) may not transfer to real payer policy text.

## What the workflow does with retrieval (Week 3)

The baseline showed retrieval confuses sibling sections inside the right policy. The Week 3 workflow therefore
uses retrieval only to choose **which policy** applies, then passes the **whole policy** (about 1,500 tokens) to the
criteria agent. That removes section-level retrieval errors from the decision path. The metric that matches this use
is "is the right policy in the top results", which the eval does not report yet.
