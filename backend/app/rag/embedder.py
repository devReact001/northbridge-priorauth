"""Embedding backends behind one small interface.

Week 2 ships a LOCAL model (runs on the client's own machine, so documents never leave
the environment). A hosted backend (for example Voyage AI) can be added later by
implementing the same three members and registering it in get_embedder(), which lets the
eval harness compare backends on accuracy, cost and latency.
"""

import hashlib
import math
import re
from typing import Protocol, Sequence


class Embedder(Protocol):
    name: str
    dim: int

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class LocalEmbedder:
    """BAAI/bge-small-en-v1.5 through sentence-transformers (384 dimensions, CPU friendly)."""

    name = "BAAI/bge-small-en-v1.5"
    dim = 384
    # BGE models retrieve better when the query (not the documents) carries this instruction.
    QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

    def __init__(self) -> None:
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.name)
        return self._model

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = self._load().encode(list(texts), normalize_embeddings=True, show_progress_bar=False)
        return [v.tolist() for v in vectors]

    def embed_query(self, text: str) -> list[float]:
        vector = self._load().encode([self.QUERY_PREFIX + text], normalize_embeddings=True)[0]
        return vector.tolist()


class HashingEmbedder:
    """Deterministic bag-of-words hashing. For unit tests only: no model download needed."""

    name = "hashing-test"
    dim = 64

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for tok in re.findall(r"[a-z0-9]+", text.lower()):
            h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
            v[h % self.dim] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


def get_embedder(kind: str = "local") -> Embedder:
    if kind == "local":
        return LocalEmbedder()
    if kind == "hashing":
        return HashingEmbedder()
    raise ValueError(f"Unknown embedder '{kind}'. Available: local, hashing")
