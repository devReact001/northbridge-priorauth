# Retrieval eval (2026-09-20 13:20, embedder: BAAI/bge-small-en-v1.5, 38 questions)

### All questions

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

### exact questions (n=8)

| mode | hit@1 | hit@3 | hit@5 | MRR |
|---|---|---|---|---|
| keyword | 100% | 100% | 100% | 1.000 |
| keyword_clean | 100% | 100% | 100% | 1.000 |
| vector | 25% | 50% | 88% | 0.463 |
| hybrid | 50% | 88% | 100% | 0.671 |
| hybrid_clean | 50% | 88% | 100% | 0.671 |
| hybrid_w3 | 38% | 62% | 88% | 0.535 |
| vector_rerank | 88% | 88% | 88% | 0.875 |
| hybrid_w3_rerank | 88% | 88% | 88% | 0.875 |

### semantic questions (n=30)

| mode | hit@1 | hit@3 | hit@5 | MRR |
|---|---|---|---|---|
| keyword | 53% | 73% | 83% | 0.653 |
| keyword_clean | 50% | 77% | 77% | 0.611 |
| vector | 90% | 97% | 100% | 0.934 |
| hybrid | 67% | 87% | 100% | 0.791 |
| hybrid_clean | 63% | 90% | 93% | 0.768 |
| hybrid_w3 | 80% | 93% | 97% | 0.862 |
| vector_rerank | 87% | 93% | 93% | 0.894 |
| hybrid_w3_rerank | 87% | 93% | 93% | 0.894 |

