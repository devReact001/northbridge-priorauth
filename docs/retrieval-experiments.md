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

## Experiments

| # | Change | Hypothesis | Result | Decision |
|---|---|---|---|---|
| 1 | `keyword_clean`: drop question words and domain-ubiquitous words from the keyword query | Keyword search improves because it matches on clinical terms and codes | _fill in_ | _fill in_ |
| 2 | `hybrid_clean`: hybrid with the cleaned keyword query | Fusion recovers most of the loss from the noisy keyword ranking | _fill in_ | _fill in_ |
| 3 | `hybrid_w3`: vector weighted 3x in fusion | A stronger retriever should count for more | _fill in_ | _fill in_ |
| 4 | 8 exact-identifier questions (CPT codes, named tests) added to the eval set | Hybrid beats vector on exact terms even if it loses on paraphrases | _fill in_ | _fill in_ |
| 5 | `vector_rerank`, `hybrid_w3_rerank`: cross-encoder reranks the top 20 | Reranking separates near-duplicate sibling sections (for example 3.2 vs 3.3) | _fill in_ | _fill in_ |

Caveats to state honestly: 38 questions is small, so one question is worth about 2.6 points and differences of
one or two questions are noise. The cleaning stoplist was written after seeing the baseline misses, so the exact
and semantic splits matter more than the overall number. A rerank model trained on web search (the default here)
may not transfer to policy text.

## What the workflow does with retrieval (Week 3)

The baseline showed retrieval confuses sibling sections inside the right policy. The Week 3 workflow therefore
uses retrieval only to choose **which policy** applies, then passes the **whole policy** (about 1,500 tokens) to the
criteria agent. That removes section-level retrieval errors from the decision path.
