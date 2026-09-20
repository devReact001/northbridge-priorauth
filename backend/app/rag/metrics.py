"""Retrieval metrics. A retrieved chunk is a hit when its (policy_id, section) is expected."""

from typing import Iterable, Sequence

Key = tuple[str, str]


def first_hit_rank(retrieved: Sequence[Key], expected: Iterable[Key]) -> int | None:
    """1-based rank of the first expected chunk in the retrieved list, or None."""
    wanted = set(expected)
    for rank, key in enumerate(retrieved, start=1):
        if key in wanted:
            return rank
    return None


def summarize(ranks: Sequence[int | None]) -> dict:
    """ranks: first_hit_rank for every question."""
    n = len(ranks)
    if n == 0:
        return {"n": 0, "hit@1": 0.0, "hit@3": 0.0, "hit@5": 0.0, "mrr": 0.0}
    return {
        "n": n,
        "hit@1": sum(1 for r in ranks if r is not None and r <= 1) / n,
        "hit@3": sum(1 for r in ranks if r is not None and r <= 3) / n,
        "hit@5": sum(1 for r in ranks if r is not None and r <= 5) / n,
        "mrr": sum(1 / r for r in ranks if r) / n,
    }
