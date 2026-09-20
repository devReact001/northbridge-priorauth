"""Score retrieval strategies on eval/retrieval_eval.jsonl.

Run from the backend/ folder (venv active, database running, policies ingested):
    python ..\\scripts\\eval_retrieval.py                       # baseline three modes
    python ..\\scripts\\eval_retrieval.py --modes all           # every experiment (downloads a reranker)
    python ..\\scripts\\eval_retrieval.py --modes vector,hybrid_w3 --show-misses

Questions have a kind: "semantic" (paraphrased questions, default) or "exact" (codes and terms
copied from the policies). Results are reported overall and per kind, and written to
eval/results.md so every change has a recorded score.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.rag import search, store  # noqa: E402
from app.rag.embedder import get_embedder  # noqa: E402
from app.rag.metrics import first_hit_rank, summarize  # noqa: E402
from app.rag.reranker import get_reranker  # noqa: E402

BASELINE_MODES = ["keyword", "vector", "hybrid"]


def load_eval(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    for r in rows:
        r.setdefault("kind", "semantic")
    return rows


def table(title: str, ranks_by_mode: dict[str, list]) -> list[str]:
    lines = [f"### {title}", "", "| mode | hit@1 | hit@3 | hit@5 | MRR |", "|---|---|---|---|---|"]
    for mode, ranks in ranks_by_mode.items():
        s = summarize(ranks)
        lines.append(f"| {mode} | {s['hit@1']:.0%} | {s['hit@3']:.0%} | {s['hit@5']:.0%} | {s['mrr']:.3f} |")
    return lines + [""]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-file", type=Path, default=ROOT / "eval" / "retrieval_eval.jsonl")
    parser.add_argument("--embedder", default="local")
    parser.add_argument("--modes", default=",".join(BASELINE_MODES), help="comma list, or 'all'")
    parser.add_argument("--show-misses", action="store_true", help="print questions each mode missed in top 3")
    args = parser.parse_args()

    modes = search.MODES if args.modes == "all" else [m.strip() for m in args.modes.split(",")]
    questions = load_eval(args.eval_file)
    embedder = get_embedder(args.embedder)
    reranker = get_reranker() if any(search.STRATEGIES[m].rerank for m in modes) else None

    ranks: dict[str, list] = {m: [] for m in modes}
    misses: dict[str, list] = {m: [] for m in modes}
    with store.connect() as conn:
        for q in questions:
            expected = [(e["policy_id"], e["section"]) for e in q["expected"]]
            for mode in modes:
                hits = search.search(conn, embedder, q["question"], top_k=5, mode=mode, reranker=reranker)
                rank = first_hit_rank([(h["policy_id"], h["section"]) for h in hits], expected)
                ranks[mode].append(rank)
                if rank is None or rank > 3:
                    got = [f"{h['policy_id']} {h['section']}" for h in hits[:3]]
                    misses[mode].append((q["id"], q["question"], expected, got))

    kinds = sorted({q["kind"] for q in questions})
    lines = [f"# Retrieval eval ({datetime.now():%Y-%m-%d %H:%M}, embedder: {embedder.name}, "
             f"{len(questions)} questions)", ""]
    lines += table("All questions", ranks)
    for kind in kinds:
        idx = [i for i, q in enumerate(questions) if q["kind"] == kind]
        lines += table(f"{kind} questions (n={len(idx)})", {m: [r[i] for i in idx] for m, r in ranks.items()})
    report = "\n".join(lines)
    print(report)
    (ROOT / "eval" / "results.md").write_text(report + "\n", encoding="utf-8")

    if args.show_misses:
        for mode in modes:
            if misses[mode]:
                print(f"\nMisses for {mode} (not in top 3):")
                for qid, question, expected, got in misses[mode]:
                    print(f"- {qid}: {question}\n    expected {expected}\n    got      {got}")


if __name__ == "__main__":
    main()
