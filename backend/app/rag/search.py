"""Hybrid retrieval: vector search + keyword search, merged with Reciprocal Rank Fusion."""

from typing import Literal, Sequence

from . import store

Mode = Literal["vector", "keyword", "hybrid"]
POOL = 20  # candidates fetched from each retriever before fusion


def rrf(rankings: Sequence[Sequence[int]], k: int = 60) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion. Each ranking is a list of ids, best first.

    score(id) = sum over rankings of 1 / (k + rank). Robust because it ignores raw scores,
    which are not comparable between cosine similarity and text-search rank.
    """
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


def search(conn, embedder, query: str, top_k: int = 5, mode: Mode = "hybrid") -> list[dict]:
    vector_hits = store.vector_search(conn, embedder.embed_query(query), POOL) if mode != "keyword" else []
    keyword_hits = store.keyword_search(conn, query, POOL) if mode != "vector" else []

    if mode == "vector":
        return vector_hits[:top_k]
    if mode == "keyword":
        return keyword_hits[:top_k]

    by_id = {h["id"]: h for h in vector_hits + keyword_hits}
    fused = rrf([[h["id"] for h in vector_hits], [h["id"] for h in keyword_hits]])
    results = []
    for chunk_id, score in fused[:top_k]:
        hit = dict(by_id[chunk_id])
        hit["score"] = score
        results.append(hit)
    return results
