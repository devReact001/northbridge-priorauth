"""Score retrieval on eval/retrieval_eval.jsonl for vector, keyword and hybrid search.

Run from the backend/ folder (venv active, database running, policies ingested):
    python ..\\scripts\\eval_retrieval.py
    python ..\\scripts\\eval_retrieval.py --show-misses

Writes eval/results.md so every change to chunking, prompts or models has a recorded score.
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

MODES = ["keyword", "vector", "hybrid"]


def load_eval(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval-file", type=Path, default=ROOT / "eval" / "retrieval_eval.jsonl")
    parser.add_argument("--embedder", default="local")
    parser.add_argument("--show-misses", action="store_true", help="print questions where hybrid missed top-3")
    args = parser.parse_args()

    questions = load_eval(args.eval_file)
    embedder = get_embedder(args.embedder)
    results: dict[str, list] = {m: [] for m in MODES}
    misses = []

    with store.connect() as conn:
        for q in questions:
            expected = [(e["policy_id"], e["section"]) for e in q["expected"]]
            for mode in MODES:
                hits = search.search(conn, embedder, q["question"], top_k=5, mode=mode)
                rank = first_hit_rank([(h["policy_id"], h["section"]) for h in hits], expected)
                results[mode].append(rank)
                if mode == "hybrid" and (rank is None or rank > 3):
                    got = [f"{h['policy_id']} {h['section']}" for h in hits[:3]]
                    misses.append((q["id"], q["question"], expected, got))

    lines = [
        f"# Retrieval eval ({datetime.now():%Y-%m-%d %H:%M}, embedder: {embedder.name}, {len(questions)} questions)",
        "",
        "| mode | hit@1 | hit@3 | hit@5 | MRR |",
        "|---|---|---|---|---|",
    ]
    for mode in MODES:
        s = summarize(results[mode])
        lines.append(f"| {mode} | {s['hit@1']:.0%} | {s['hit@3']:.0%} | {s['hit@5']:.0%} | {s['mrr']:.3f} |")
    report = "\n".join(lines)
    print(report)
    (ROOT / "eval" / "results.md").write_text(report + "\n", encoding="utf-8")

    if args.show_misses and misses:
        print("\nHybrid misses (not in top 3):")
        for qid, question, expected, got in misses:
            print(f"- {qid}: {question}\n    expected {expected}\n    got      {got}")


if __name__ == "__main__":
    main()
