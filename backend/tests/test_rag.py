"""RAG tests that need no database and no model download."""

import json
from pathlib import Path

import pytest

from app.rag.chunking import chunk_directory
from app.rag.embedder import HashingEmbedder
from app.rag.metrics import first_hit_rank, summarize
from app.rag.reranker import apply_scores
from app.rag.search import STRATEGIES, rrf
from app.rag.store import build_or_tsquery, clean_terms, vec_literal

ROOT = Path(__file__).resolve().parents[2]
PDF_DIR = ROOT / "policies" / "pdf"
EVAL_FILE = ROOT / "eval" / "retrieval_eval.jsonl"


def _chunks():
    return chunk_directory(PDF_DIR)


def _questions():
    return [json.loads(line) for line in EVAL_FILE.read_text().splitlines() if line.strip()]


def test_all_four_policies_are_chunked():
    assert {c.policy_id for c in _chunks()} == {"MP-IMG-001", "MP-IMG-002", "MP-IMG-003", "MP-GEN-001"}


def test_titles_that_wrap_onto_two_lines_are_captured_whole():
    titles = {c.policy_id: c.policy_title for c in _chunks()}
    assert titles["MP-GEN-001"] == "General Prior Authorization Requirements"


def test_chunks_carry_context_header_and_no_footer_noise():
    for c in _chunks():
        assert c.text.startswith(f"{c.policy_id} ")
        assert "Fictional policy for portfolio use. Not clinical guidance. Page" not in c.text
        assert len(c.text) > 60


def test_every_eval_question_points_at_a_real_section():
    """Guards the eval set itself: an expected section that does not exist would score 0% forever."""
    available = {c.key for c in _chunks()}
    questions = _questions()
    assert len(questions) == 38
    for q in questions:
        for e in q["expected"]:
            assert (e["policy_id"], e["section"]) in available, f"{q['id']} expects a missing section"


def test_eval_question_ids_are_unique_and_kinds_are_known():
    qs = _questions()
    assert len({q["id"] for q in qs}) == len(qs)
    kinds = [q.get("kind", "semantic") for q in qs]
    assert set(kinds) == {"semantic", "exact"} and kinds.count("exact") == 8


def test_rrf_rewards_agreement_between_rankings():
    order = [item for item, _ in rrf([[1, 2, 3], [3, 1, 4]])]
    assert order[0] == 1 and set(order) == {1, 2, 3, 4}


def test_rrf_with_one_empty_ranking_keeps_the_other():
    assert [i for i, _ in rrf([[7, 8], []])] == [7, 8]


def test_weighted_rrf_lets_the_stronger_retriever_win_a_disagreement():
    a, b = [1, 2], [2, 1]  # the two retrievers disagree about the top result
    assert rrf([a, b], weights=[1, 1])[0][0] == 1  # tie broken by id
    assert rrf([a, b], weights=[3, 1])[0][0] == 1  # vector (first) wins when weighted up
    assert rrf([a, b], weights=[1, 3])[0][0] == 2  # keyword wins when weighted up


def test_first_hit_rank_and_summary():
    expected = [("MP-IMG-001", "3.1")]
    assert first_hit_rank([("A", "1"), ("MP-IMG-001", "3.1")], expected) == 2
    assert first_hit_rank([("A", "1")], expected) is None
    s = summarize([1, 2, None, 5])
    assert s["hit@1"] == 0.25 and s["hit@3"] == 0.5 and s["hit@5"] == 0.75
    assert abs(s["mrr"] - (1 + 0.5 + 0.2) / 4) < 1e-9


def test_raw_and_clean_keyword_queries():
    q = "Can we ask, after the scan?"
    assert build_or_tsquery(q) == "can | we | ask | after | the | scan"
    assert build_or_tsquery(q, clean=True) == "ask | scan"
    assert clean_terms("How long do we have to appeal? CPT 73721") == ["appeal", "cpt", "73721"]
    assert vec_literal([0.5, 0.25]) == "[0.500000,0.250000]"


def test_apply_scores_sorts_best_first_and_keeps_fields():
    hits = [{"id": 1, "content": "a", "score": 0.1}, {"id": 2, "content": "b", "score": 0.2}]
    ranked = apply_scores(hits, [0.3, 0.9])
    assert [h["id"] for h in ranked] == [2, 1] and ranked[0]["score"] == 0.9 and hits[0]["score"] == 0.1


def test_strategy_table_covers_every_experiment():
    assert {"keyword", "vector", "hybrid", "hybrid_clean", "hybrid_w3", "vector_rerank"} <= set(STRATEGIES)
    assert STRATEGIES["hybrid"].weights == (1.0, 1.0) and STRATEGIES["hybrid_w3"].weights == (3.0, 1.0)
    assert STRATEGIES["hybrid_w3_rerank"].rerank and not STRATEGIES["vector"].rerank


def test_unknown_search_mode_is_rejected():
    from app.rag.search import search

    with pytest.raises(ValueError):
        search(None, HashingEmbedder(), "x", mode="magic")


def test_hashing_embedder_shape_and_determinism():
    e = HashingEmbedder()
    a, b = e.embed_query("lumbar mri"), e.embed_query("lumbar mri")
    assert a == b and len(a) == e.dim
