"""RAG tests that need no database and no model download."""

import json
from pathlib import Path

from app.rag.chunking import chunk_directory
from app.rag.embedder import HashingEmbedder
from app.rag.metrics import first_hit_rank, summarize
from app.rag.search import rrf
from app.rag.store import build_or_tsquery, vec_literal

ROOT = Path(__file__).resolve().parents[2]
PDF_DIR = ROOT / "policies" / "pdf"
EVAL_FILE = ROOT / "eval" / "retrieval_eval.jsonl"


def _chunks():
    return chunk_directory(PDF_DIR)


def test_all_four_policies_are_chunked():
    ids = {c.policy_id for c in _chunks()}
    assert ids == {"MP-IMG-001", "MP-IMG-002", "MP-IMG-003", "MP-GEN-001"}


def test_chunks_carry_context_header_and_no_footer_noise():
    for c in _chunks():
        assert c.text.startswith(f"{c.policy_id} ")
        assert "Fictional policy for portfolio use. Not clinical guidance. Page" not in c.text
        assert len(c.text) > 60


def test_every_eval_question_points_at_a_real_section():
    """Guards the eval set itself: an expected section that does not exist would score 0% forever."""
    available = {c.key for c in _chunks()}
    questions = [json.loads(line) for line in EVAL_FILE.read_text().splitlines() if line.strip()]
    assert len(questions) == 30
    for q in questions:
        for e in q["expected"]:
            assert (e["policy_id"], e["section"]) in available, f"{q['id']} expects a missing section"


def test_eval_question_ids_are_unique():
    ids = [json.loads(line)["id"] for line in EVAL_FILE.read_text().splitlines() if line.strip()]
    assert len(ids) == len(set(ids))


def test_rrf_rewards_agreement_between_rankings():
    fused = rrf([[1, 2, 3], [3, 1, 4]])
    order = [item for item, _ in fused]
    assert order[0] == 1  # near the top of both lists
    assert set(order) == {1, 2, 3, 4}


def test_rrf_with_one_empty_ranking_keeps_the_other():
    assert [i for i, _ in rrf([[7, 8], []])] == [7, 8]


def test_first_hit_rank_and_summary():
    expected = [("MP-IMG-001", "3.1")]
    assert first_hit_rank([("A", "1"), ("MP-IMG-001", "3.1")], expected) == 2
    assert first_hit_rank([("A", "1")], expected) is None
    s = summarize([1, 2, None, 5])
    assert s["hit@1"] == 0.25 and s["hit@3"] == 0.5 and s["hit@5"] == 0.75
    assert abs(s["mrr"] - (1 + 0.5 + 0.2) / 4) < 1e-9


def test_or_tsquery_and_vector_literal():
    assert build_or_tsquery("Can we ask, after the scan?") == "can | we | ask | after | the | scan"
    assert vec_literal([0.5, 0.25]) == "[0.500000,0.250000]"


def test_hashing_embedder_shape_and_determinism():
    e = HashingEmbedder()
    a, b = e.embed_query("lumbar mri"), e.embed_query("lumbar mri")
    assert a == b and len(a) == e.dim
