"""Cross-encoder reranking: reads (query, passage) pairs together, so it can separate
near-duplicate sibling sections that a bi-encoder embedding scores almost identically."""

from typing import Protocol, Sequence


class Reranker(Protocol):
    name: str

    def rerank(self, query: str, hits: Sequence[dict]) -> list[dict]: ...


def apply_scores(hits: Sequence[dict], scores: Sequence[float]) -> list[dict]:
    """Attach reranker scores and sort best first. Pure function, unit tested."""
    ranked = []
    for hit, score in zip(hits, scores):
        h = dict(hit)
        h["score"] = float(score)
        ranked.append(h)
    return sorted(ranked, key=lambda h: -h["score"])


class CrossEncoderReranker:
    """Small general-purpose cross-encoder (about 90 MB). A healthcare-specific or larger
    reranker may do better; swap `name` and compare on the eval set."""

    name = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    def __init__(self) -> None:
        self._model = None

    def rerank(self, query: str, hits: Sequence[dict]) -> list[dict]:
        if not hits:
            return []
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.name)
        scores = self._model.predict([(query, h["content"]) for h in hits])
        return apply_scores(hits, scores)


def get_reranker(kind: str = "cross-encoder") -> Reranker:
    if kind == "cross-encoder":
        return CrossEncoderReranker()
    raise ValueError(f"Unknown reranker '{kind}'. Available: cross-encoder")
