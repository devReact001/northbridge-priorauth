"""Week 6: per-step models, and the lean and split assessments. The variants must give the same assessment as the
full one, because every guardrail and the recommendation run on the expanded result."""

import copy
import json
from types import SimpleNamespace

from langgraph.checkpoint.memory import MemorySaver

from app.agents import criteria
from app.schemas import IntakeResult
from app.workflow.graph import Deps, build_graph, start_case
from test_workflow import DRAFT, NOTE, FakeLLM, _criteria, _intake, _policy_chunks


def to_lean(full: dict) -> dict:
    """What a model would write against the lean schema for the same findings."""
    def req(r, general=False):
        out = {"requirement": r["requirement"], "status": r["status"],
               "quotes": [e["source_quote"] for e in r["evidence"]], "rationale": r["rationale"]}
        if general:
            out.update(policy_id=r["policy_id"], section=r["section"])
        return out

    return {
        "policy_applies": full["policy_applies"], "applicable_policy_id": full["applicable_policy_id"],
        "pathways": [{"name": p["name"], "policy_id": p["policy_id"], "section": p["section"],
                      "requirements": [req(r) for r in p["requirements"]]} for p in full["pathways"]],
        "exclusions_triggered": [{k: v for k, v in e.items() if k != "source"} for e in full["exclusions_triggered"]],
        "general_requirements": [req(r, True) for r in full["general_requirements"]],
        "summary": full["summary"],
    }


def to_split(full: dict) -> tuple[dict, dict]:
    lean = to_lean(full)
    general = lean.pop("general_requirements")
    return lean, {"general_requirements": general}


class ModelSpy(FakeLLM):
    """A fake model that also records which model each tool call asked for."""

    def __init__(self, **payloads):
        super().__init__(**payloads)
        self.models: dict[str, str] = {}

    def create(self, **kwargs):
        self.models[kwargs["tools"][0]["name"]] = kwargs["model"]
        return super().create(**kwargs)


def _run(llm, **kw):
    intake = IntakeResult.model_validate(_intake())
    return criteria.assess(NOTE, intake, _policy_chunks(), "2026-03-20", client=llm, model="m", **kw)


def _shape(result):
    """Everything a reviewer or the decision can see, minus the model-written `finding` text the lean form drops."""
    a = result.assessment
    return {
        "recommendation": result.recommendation, "notes": result.guardrail_notes, "summary": a.summary,
        "pathways": [(p.name, p.policy_id, p.section,
                      [(r.requirement, r.status, r.policy_id, r.section, [e.source_quote for e in r.evidence],
                        r.evidence_sources) for r in p.requirements]) for p in a.pathways],
        "general": [(r.requirement, r.status, r.policy_id, r.section, [e.source_quote for e in r.evidence],
                     r.evidence_sources) for r in a.general_requirements],
        "exclusions": [(e.policy_id, e.section, e.basis, e.source) for e in a.exclusions_triggered],
    }


def test_lean_assessment_equals_the_full_one():
    full, _ = _run(FakeLLM())
    lean, call = _run(FakeLLM(record_criteria=to_lean(_criteria())), lean=True)
    assert _shape(lean) == _shape(full)
    assert lean.recommendation == "likely_meets" and lean.guardrail_notes == []
    assert call.input_tokens == 100


def test_split_assessment_equals_the_full_one_and_makes_two_calls():
    full, _ = _run(FakeLLM())
    part_a, part_b = to_split(_criteria())
    llm = FakeLLM(record_pathways=part_a, record_general=part_b)
    split, call = _run(llm, split=True)
    assert _shape(split) == _shape(full)
    assert sorted(llm.calls) == ["record_general", "record_pathways"]
    assert call.input_tokens == 200 and call.output_tokens == 100, "tokens of both calls are added"


def test_the_guardrails_still_catch_a_bad_quote_in_lean_and_split_modes():
    bad = _criteria()
    bad["pathways"][0]["requirements"][0]["evidence"][0]["source_quote"] = "Reports a locked knee since Tuesday"
    full, _ = _run(FakeLLM(record_criteria=bad))
    lean, _ = _run(FakeLLM(record_criteria=to_lean(bad)), lean=True)
    a, b = to_split(bad)
    split, _ = _run(FakeLLM(record_pathways=a, record_general=b), split=True)
    assert _shape(lean) == _shape(full) == _shape(split)
    assert any("dropped a quote" in n for n in split.guardrail_notes)
    assert split.recommendation == "needs_more_info"


def test_split_drops_the_general_part_when_the_policy_does_not_apply():
    a, b = to_split(_criteria(policy_applies=False, pathways=[], applicable_policy_id=None))
    split, _ = _run(FakeLLM(record_pathways=a, record_general=b), split=True)
    assert split.recommendation == "no_applicable_policy" and split.assessment.general_requirements == []


def test_split_reports_an_empty_pathway_list_twice_as_a_default_not_a_finding():
    a, b = to_split(_criteria(pathways=[]))
    split, _ = _run(FakeLLM(record_pathways=a, record_general=b), split=True)
    assert split.recommendation == "needs_more_info"
    assert any("no pathways twice" in n for n in split.guardrail_notes)


def test_the_lean_form_is_shorter_for_the_model_to_write():
    full, lean = json.dumps(_criteria()), json.dumps(to_lean(_criteria()))
    assert len(lean) < 0.8 * len(full)
    assert len(json.dumps(criteria.TOOL_LEAN)) < len(json.dumps(criteria.TOOL))


def test_each_step_uses_its_own_model_and_records_it_in_the_trace():
    llm = ModelSpy()
    deps = Deps(retrieve_policy=lambda i: ("MP-IMG-002", _policy_chunks()), llm_client=llm, model="default-model",
                step_models={"assess": "assess-model", "draft": "draft-model"})
    view = start_case(build_graph(deps, MemorySaver()), NOTE, request_date="2026-03-20")
    assert llm.models == {"record_intake": "default-model", "record_criteria": "assess-model",
                          "record_draft": "draft-model"}
    used = {e["node"]: e["detail"].get("model") for e in view["trace"] if e["node"] in ("intake", "assess", "draft")}
    assert used == {"intake": "default-model", "assess": "assess-model", "draft": "draft-model"}
    assert next(e for e in view["trace"] if e["node"] == "assess")["detail"]["mode"] == "full"


def test_the_workflow_runs_end_to_end_in_split_mode():
    a, b = to_split(_criteria())
    llm = FakeLLM(record_pathways=a, record_general=b)
    deps = Deps(retrieve_policy=lambda i: ("MP-IMG-002", _policy_chunks()), llm_client=llm, model="m", assess_split=True)
    view = start_case(build_graph(deps, MemorySaver()), NOTE, request_date="2026-03-20")
    assert view["status"] == "awaiting_review" and view["recommendation"] == "likely_meets"
    assert next(e for e in view["trace"] if e["node"] == "assess")["detail"]["mode"] == "split"
