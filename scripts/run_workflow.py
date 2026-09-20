"""Run the full workflow on one note, with the human review step in the terminal.

Needs: database running with policies ingested, ANTHROPIC_API_KEY in .env.
From the backend/ folder (venv active):
    python ..\\scripts\\run_workflow.py app\\data\\sample_notes\\note_03_knee_meets.txt
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.workflow.graph import resume_case, start_case  # noqa: E402
from app.workflow.runtime import get_workflow, persist_view  # noqa: E402

MARK = {"met": "[met]     ", "not_met": "[NOT MET] ", "unclear": "[unclear] ", "not_applicable": "[n/a]     "}


def show_packet(view: dict) -> None:
    p = view["packet"]
    print(f"\nCase {view['case_id']}   recommendation: {p['recommendation'] or 'none (escalated)'}")
    if p["escalation_reason"]:
        print(f"ESCALATED: {p['escalation_reason']}")
    i = p["intake"]
    print(f"Procedure: {i['requested_procedure']} (CPT {i['procedure_code'] or 'not stated'})   extraction confidence: {i['confidence']}")
    if p.get("summary"):
        print(f"Summary: {p['summary']}")
    for pw in p.get("pathways", []):
        print(f"\n  Pathway {pw['cite']}: {pw['name']}  -> {pw['status'].upper()}")
        for r in pw["requirements"]:
            print(f"    {MARK[r['status']]}{r['requirement']}")
            for q in r["quotes"]:
                print(f'                 "{q}"')
    for r in p.get("general_requirements", []):
        print(f"  general {MARK[r['status']]}{r['requirement']}")
    for e in p.get("exclusions_triggered", []):
        print(f"  EXCLUSION ({e['basis']}) {e['policy_id']} section {e['section']}: {e['reason']}")
    for n in p.get("guardrail_notes", []):
        print(f"  guardrail: {n}")
    if p["draft"]:
        d = p["draft"]
        print(f"\n--- DRAFT ({d['kind']}) ---\n{d['subject']}\n\n{d['body']}")
        for w in d["warnings"]:
            print(f"  WARNING: {w}")
    print()


def ask_decision(allowed: list[str]) -> dict:
    letters = {a[0]: a for a in allowed}
    while True:
        choice = input(f"Decision: {' / '.join(f'[{a[0]}]{a[1:]}' for a in allowed)} > ").strip().lower()[:1]
        if choice in letters:
            break
    reviewer = input("Reviewer name > ").strip() or "reviewer"
    notes = input("Notes (optional) > ").strip()
    decision = {"action": letters[choice], "reviewer": reviewer, "notes": notes}
    if decision["action"] == "edit":
        print("Type the final document. Finish with a line containing only END")
        lines = []
        while (line := input()) != "END":
            lines.append(line)
        decision["edited_letter"] = "\n".join(lines)
    return decision


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("note", type=Path)
    parser.add_argument("--request-date", default=None, help="YYYY-MM-DD, defaults to today")
    args = parser.parse_args()

    graph = get_workflow()
    view = start_case(graph, args.note.read_text(encoding="utf-8"), args.note.name, args.request_date)
    persist_view(view)
    show_packet(view)
    done = resume_case(graph, view["case_id"], ask_decision(view["packet"]["allowed_actions"]))
    persist_view(done)
    print(f"\nFinal status: {done['status']}")
    if done["final_document"]:
        print(f"\n{done['final_document']}")
    print("\nTrace:")
    for e in done["trace"]:
        print(f"  {e['node']:<13}{e['latency_ms']:>6} ms  {e['input_tokens']:>5} in  {e['output_tokens']:>5} out")


if __name__ == "__main__":
    main()
