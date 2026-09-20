"""Compare settings (models per step, lean and split assessment) on the sample notes.

Runs each note under each profile up to the human-review pause (nothing is approved or sent), then prints a table:
wall time, assess time, tokens, cost, and whether the recommendation and every pathway status match the first
profile. Use --repeats 2 or more so the first profile's own run-to-run variation shows up next to the differences.

Needs: database running with policies ingested, ANTHROPIC_API_KEY in .env. Real API calls: each run is about
70 s and costs a few cents. From the backend/ folder (venv active):

    python ..\\scripts\\compare_models.py --profiles baseline,lean,split --notes note_03,note_06,note_02
    python ..\\scripts\\compare_models.py --profiles baseline,all_sonnet --repeats 2 --out ..\\eval\\comparison.json
    python ..\\scripts\\compare_models.py --profiles "baseline,mix:intake=claude-haiku-4-5,assess=claude-sonnet-4-5,split=1"

A profile is a preset name or 'label:key=value,...' with keys model, intake, ehr, assess, draft, lean, split.
"""

import argparse
import json
import re
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from langgraph.checkpoint.memory import MemorySaver  # noqa: E402

from app.config import BACKEND_DIR, settings  # noqa: E402
from app.rag import search  # noqa: E402
from app.rag.embedder import get_embedder  # noqa: E402
from app.rag.reranker import get_reranker  # noqa: E402
from app.workflow import compare  # noqa: E402
from app.workflow.graph import Deps, build_graph, start_case  # noqa: E402
from app.workflow.runtime import make_ehr_tools, make_retrieve_policy  # noqa: E402

SONNET = "claude-sonnet-4-5"
PRESETS = {  # "baseline" uses ANTHROPIC_MODEL from .env, which is Haiku by default
    "baseline": {},
    "lean": {"lean": "1"},
    "split": {"split": "1"},
    "sonnet_assess": {"assess": SONNET},
    "split_sonnet_assess": {"split": "1", "assess": SONNET},
    "all_sonnet": {"model": SONNET},
}
SAMPLES = BACKEND_DIR / "app" / "data" / "sample_notes"


def parse_profile(spec: str) -> tuple[str, dict]:
    if ":" in spec:
        label, rest = spec.split(":", 1)
        return label, dict(kv.split("=", 1) for kv in rest.split(",") if kv)
    if spec not in PRESETS:
        sys.exit(f"Unknown profile '{spec}'. Presets: {', '.join(PRESETS)}. Or use 'label:key=value,...'.")
    return spec, PRESETS[spec]


def make_deps(opts: dict, retrieve, ehr_tools) -> Deps:
    on = lambda k: opts.get(k, "0").lower() in ("1", "true", "yes")  # noqa: E731
    return Deps(
        retrieve_policy=retrieve, ehr_tools=ehr_tools, model=opts.get("model"),
        step_models={s: opts[s] for s in ("intake", "ehr", "assess", "draft") if opts.get(s)},
        assess_lean=on("lean"), assess_split=on("split"),
    )


def pick_notes(spec: str) -> list[tuple[str, str, str]]:
    files = sorted(SAMPLES.glob("*.txt"))
    if spec != "all":
        wanted = spec.split(",")
        files = [f for f in files if any(f.name.startswith(w) or w in f.name for w in wanted)]
    if not files:
        sys.exit("No sample notes matched --notes.")
    out = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        visit = re.search(r"Date of visit:\s*(\d{4}-\d{2}-\d{2})", text)
        out.append((f.name, text, visit.group(1) if visit else "2026-03-20"))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profiles", default="baseline,lean,split")
    ap.add_argument("--notes", default="all", help="'all' or comma-separated name fragments, e.g. note_03,note_06")
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--out", help="write the raw runs and the table as JSON")
    ap.add_argument("--price", action="append", default=[], metavar="MODEL=IN,OUT",
                    help="USD per million tokens, e.g. claude-opus-4-5=5,25 (list prices change; check them)")
    args = ap.parse_args()
    if not settings.anthropic_api_key or not settings.database_url:
        sys.exit("ANTHROPIC_API_KEY and DATABASE_URL must be set in .env (this makes real API calls).")

    prices = dict(compare.PRICES)
    for p in args.price:
        model, vals = p.split("=", 1)
        prices[model] = tuple(float(v) for v in vals.split(","))
    profiles = [parse_profile(s.strip()) for s in re.split(r",(?=[a-z_0-9]+(?::|,|$))", args.profiles) if s.strip()]
    notes = pick_notes(args.notes)
    total = len(profiles) * len(notes) * args.repeats
    print(f"{len(profiles)} profiles x {len(notes)} notes x {args.repeats} repeats = {total} runs (about {total * 70 // 60} min)\n")

    reranker = get_reranker() if search.STRATEGIES[settings.retrieval_mode].rerank else None
    retrieve = make_retrieve_policy(get_embedder("local"), settings.retrieval_mode, reranker)
    ehr_tools = make_ehr_tools()

    runs: dict[str, list[dict]] = {name: [] for name, _ in profiles}
    n = 0
    # Repeats of one note run back to back for every profile, so a slow patch on the API hits all profiles alike.
    for note_name, text, request_date in notes:
        for repeat in range(args.repeats):
            for name, opts in profiles:
                n += 1
                graph = build_graph(make_deps(opts, retrieve, ehr_tools), MemorySaver())
                start = time.perf_counter()
                try:
                    view = start_case(graph, text, note_name, request_date, case_id=uuid.uuid4().hex[:12])
                    rec = compare.run_record(note_name, repeat, view, int((time.perf_counter() - start) * 1000), prices)
                    print(f"[{n}/{total}] {name:<18} {note_name:<32} {rec['wall_ms'] / 1000:5.1f} s  {rec['recommendation']}")
                    ref = next((r for r in runs[profiles[0][0]] if r["ok"] and r["note"] == note_name and r["repeat"] == 0), None)
                    if ref is not None and ref is not rec:
                        for d in compare.differences(ref, rec):
                            print(f"        differs from the reference run: {d}")
                except Exception as e:  # noqa: BLE001  one failed run must not lose the rest
                    rec = compare.failed_record(note_name, repeat, f"{type(e).__name__}: {e}")
                    print(f"[{n}/{total}] {name:<18} {note_name:<32} FAILED  {rec['error']}")
                runs[name].append(rec)

    rows = compare.summarize(runs)
    print("\n" + compare.markdown(rows))
    print("\nsame_* compares with the first profile; its own row shows how much the answer moves between repeats.")
    if args.out:
        Path(args.out).write_text(json.dumps({"profiles": dict(profiles), "rows": rows, "runs": runs}, indent=1), encoding="utf-8")
        print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
