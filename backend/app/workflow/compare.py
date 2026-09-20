"""Week 6: turn repeated runs of the workflow under different settings into a comparison table.

Pure functions over finished case views, so they are tested without a model. scripts/compare_models.py does the
running. The question the numbers answer: does a faster setting change what the reviewer is told?
"""

from typing import Optional

from .metrics import percentile

# USD per million tokens (input, output). Published list prices change: check them before quoting a cost, and
# override with --price on the command line. A model that is not listed reports no cost rather than a guess.
PRICES: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}

LLM_STEPS = ("intake", "ehr", "assess", "draft")


def step_cost(model: Optional[str], tokens_in: int, tokens_out: int, prices: dict) -> Optional[float]:
    if model not in prices:
        return None
    p_in, p_out = prices[model]
    return (tokens_in * p_in + tokens_out * p_out) / 1_000_000


def run_record(note: str, repeat: int, view: dict, wall_ms: int, prices: dict = PRICES) -> dict:
    """Everything worth comparing about one finished run, from the case view the API would return."""
    packet = view.get("packet") or {}
    steps: dict[str, dict] = {}
    costs: list[Optional[float]] = []
    for e in view.get("trace", []):
        if e["node"] not in LLM_STEPS:
            continue
        model = (e.get("detail") or {}).get("model")
        steps[e["node"]] = {"latency_ms": e["latency_ms"], "input_tokens": e["input_tokens"],
                            "output_tokens": e["output_tokens"], "model": model}
        costs.append(step_cost(model, e["input_tokens"], e["output_tokens"], prices))
    general = packet.get("general_requirements", [])
    return {
        "note": note, "repeat": repeat, "ok": True, "wall_ms": wall_ms,
        "recommendation": view.get("recommendation"),
        "pathways": {p["cite"]: p["status"] for p in packet.get("pathways", [])},
        "general_met": sum(1 for r in general if r["status"] == "met"), "general_total": len(general),
        "guardrail_notes": len(packet.get("guardrail_notes", [])),
        "steps": steps,
        "cost_usd": None if not costs or any(c is None for c in costs) else round(sum(costs), 4),
    }


def failed_record(note: str, repeat: int, error: str) -> dict:
    return {"note": note, "repeat": repeat, "ok": False, "error": error}


def agrees(reference: dict, other: dict) -> tuple[bool, bool]:
    """(same recommendation, same status on every pathway). Both records must be successful runs."""
    return (reference["recommendation"] == other["recommendation"], reference["pathways"] == other["pathways"])


def differences(reference: dict, other: dict) -> list[str]:
    """What changed between two successful runs of the same note, in words, for the run log."""
    out = []
    if reference["recommendation"] != other["recommendation"]:
        out.append(f"recommendation {reference['recommendation']} -> {other['recommendation']}")
    for cite in sorted(set(reference["pathways"]) | set(other["pathways"])):
        a, b = reference["pathways"].get(cite), other["pathways"].get(cite)
        if a != b:
            out.append(f"pathway {cite}: {a or 'absent'} -> {b or 'absent'}")
    return out


def _mean(values: list) -> Optional[float]:
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 4) if values else None


def summarize(runs_by_profile: dict[str, list[dict]]) -> list[dict]:
    """One row per profile. The first profile is the reference: every other run is compared with the reference
    run of the same note. The reference's own repeats are compared with its first run, which shows how much the
    answer moves from run to run with nothing changed. That is the noise floor for reading the other rows."""
    profiles = list(runs_by_profile)
    reference = {r["note"]: r for r in runs_by_profile[profiles[0]] if r["ok"] and r["repeat"] == 0}
    rows = []
    for name in profiles:
        runs = runs_by_profile[name]
        ok = [r for r in runs if r["ok"]]
        rec = [0, 0]
        path = [0, 0]
        for r in ok:
            ref = reference.get(r["note"])
            if ref is None or r is ref:
                continue
            same_rec, same_path = agrees(ref, r)
            rec[0] += same_rec
            rec[1] += 1
            path[0] += same_path
            path[1] += 1
        walls = [r["wall_ms"] for r in ok]
        assess = [r["steps"]["assess"]["latency_ms"] for r in ok if "assess" in r["steps"]]
        rows.append({
            "profile": name, "runs": len(runs), "failed": len(runs) - len(ok),
            "wall_p50_s": _s(percentile(walls, 50)), "wall_max_s": _s(max(walls) if walls else None),
            "assess_p50_s": _s(percentile(assess, 50)),
            "output_tokens_mean": _mean([sum(s["output_tokens"] for s in r["steps"].values()) for r in ok]),
            "cost_mean_usd": _mean([r["cost_usd"] for r in ok]),
            "same_recommendation": f"{rec[0]}/{rec[1]}" if rec[1] else "reference",
            "same_pathways": f"{path[0]}/{path[1]}" if path[1] else "reference",
            "guardrail_notes_mean": _mean([r["guardrail_notes"] for r in ok]),
        })
    return rows


def _s(ms: Optional[float]) -> Optional[float]:
    return None if ms is None else round(ms / 1000, 1)


def markdown(rows: list[dict]) -> str:
    heads = ["profile", "runs", "failed", "wall_p50_s", "wall_max_s", "assess_p50_s", "output_tokens_mean",
             "cost_mean_usd", "same_recommendation", "same_pathways", "guardrail_notes_mean"]
    lines = ["| " + " | ".join(heads) + " |", "|" + "---|" * len(heads)]
    for r in rows:
        lines.append("| " + " | ".join("n/a" if r[h] is None else str(r[h]) for h in heads) + " |")
    return "\n".join(lines)
