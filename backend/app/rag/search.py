"""Retrieval strategies: vector, keyword, hybrid (Reciprocal Rank Fusion), optional reranking.

Each named strategy is one experiment, so the eval script can score them side by side and
docs/retrieval-experiments.md can record what each change did.
"""

from dataclasses import dataclass
from typing import Optional, Sequence

from . import store

POOL = 20  # candidates fetched from each retriever before fusion / reranking


def rrf(rankings: Sequence[Sequence[int]], k: int = 60, weights: Optional[Sequence[float]] = None) -> list[tuple[int, float]]:
    """Weighted Reciprocal Rank Fusion. Each ranking is a list of ids, best first.

    score(id) = sum over rankings of weight / (k + rank). Ignores raw scores, which are not
    comparable between cosine similarity and text-search rank. Weights let a stronger retriever
    count for more than a weaker one.
    """
    weights = list(weights) if weights is not None else [1.0] * len(rankings)
    scores: dict[int, float] = {}
    for weight, ranking in zip(weights, rankings):
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + weight / (k + rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


@dataclass(frozen=True)
class Strategy:
    vector: bool
    keyword: Optional[str] = None  # None, "raw" (all words) or "clean" (question words removed)
    weights: tuple[float, float] = (1.0, 1.0)  # (vector, keyword) weights when both are used
    rerank: bool = False


STRATEGIES: dict[str, Strategy] = {
    "keyword": Strategy(vector=False, keyword="raw"),
    "keyword_clean": Strategy(vector=False, keyword="clean"),
    "vector": Strategy(vector=True),
    "hybrid": Strategy(vector=True, keyword="raw"),  # Week 2 baseline
    "hybrid_clean": Strategy(vector=True, keyword="clean"),
    "hybrid_w3": Strategy(vector=True, keyword="clean", weights=(3.0, 1.0)),
    "vector_rerank": Strategy(vector=True, rerank=True),
    "hybrid_w3_rerank": Strategy(vector=True, keyword="clean", weights=(3.0, 1.0), rerank=True),
}
MODES = list(STRATEGIES)


def search(conn, embedder, query: str, top_k: int = 5, mode: str = "hybrid", reranker=None) -> list[dict]:
    if mode not in STRATEGIES:
        raise ValueError(f"Unknown mode '{mode}'. Available: {', '.join(MODES)}")
    s = STRATEGIES[mode]
    if s.rerank and reranker is None:
        raise ValueError(f"Mode '{mode}' needs a reranker")

    vector_hits = store.vector_search(conn, embedder.embed_query(query), POOL) if s.vector else []
    keyword_hits = store.keyword_search(conn, query, POOL, clean=(s.keyword == "clean")) if s.keyword else []

    if s.vector and s.keyword:
        by_id = {h["id"]: h for h in vector_hits + keyword_hits}
        fused = rrf([[h["id"] for h in vector_hits], [h["id"] for h in keyword_hits]], weights=s.weights)
        candidates = []
        for chunk_id, score in fused:
            hit = dict(by_id[chunk_id])
            hit["score"] = score
            candidates.append(hit)
    else:
        candidates = vector_hits or keyword_hits

    if s.rerank:
        candidates = reranker.rerank(query, candidates[:POOL])
    return candidates[:top_k]
