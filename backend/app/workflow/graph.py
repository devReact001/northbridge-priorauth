r"""The prior-authorization workflow as a LangGraph state machine.

    intake -> policy -> assess -> draft -> human_review -> finalize
       \        \         \                    ^
        +--------+---------+--> escalate ------+

Design decisions worth defending in an interview:
- Agents (intake, assess, draft) do the language work. ROUTING is plain code, because routing is the
  safety-critical part and should be deterministic, testable and explainable.
- There is no edge from any agent to `finalize`. Every case, including escalations, passes through
  `human_review`, which pauses the graph with interrupt() until a person decides.
- The graph is pure: its dependencies (LLM client, policy retrieval) are injected, so tests run with
  fakes and no network.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable, Optional

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from ..agents import criteria, drafter
from ..agents.intake import run_intake
from ..schemas import IntakeResponse, IntakeResult
from .state import CaseState, ReviewDecision

ESCALATE_CONFIDENCE = 0.5

# retrieve_policy(intake) -> (policy_id or None, chunks of that policy plus the general sections)
RetrievePolicy = Callable[[IntakeResult], tuple[Optional[str], list[dict]]]


class NotAwaitingReview(Exception):
    """Raised when a review is submitted for a case that is not paused for review."""


@dataclass
class Deps:
    retrieve_policy: RetrievePolicy
    llm_client: Any = None
    model: Optional[str] = None
    intake_fn: Optional[Callable[[str], IntakeResponse]] = None


def _event(node: str, latency_ms: int = 0, input_tokens: int = 0, output_tokens: int = 0, **detail) -> dict:
    return {
        "node": node,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "latency_ms": latency_ms,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "detail": detail,
    }


def escalation_reason(state: CaseState) -> Optional[str]:
    """Why (if at all) the case must skip straight to a human. Pure function of the state."""
    result = state.get("intake", {}).get("result", {})
    if result.get("confidence", 0) < ESCALATE_CONFIDENCE or not result.get("requested_procedure"):
        return (
            f"Extraction confidence is below {ESCALATE_CONFIDENCE} or no requested procedure was found "
            "in the note."
        )
    if "policy_chunks" in state and not state["policy_chunks"]:
        return "No payer policy matched the requested procedure."
    if state.get("assessment", {}).get("recommendation") == "no_applicable_policy":
        return "The closest payer policy does not cover the requested procedure."
    return None


def build_packet(state: CaseState) -> dict:
    """The review packet a human sees. Built from state only, so it is identical on every resume."""
    intake = state.get("intake", {})
    result = intake.get("result", {})
    assessment = state.get("assessment")
    draft = state.get("draft")
    packet: dict[str, Any] = {
        "case_id": state.get("case_id"),
        "escalation_reason": state.get("escalation_reason"),
        "intake": {
            "requested_procedure": result.get("requested_procedure"),
            "procedure_code": result.get("procedure_code"),
            "diagnoses": result.get("diagnoses", []),
            "confidence": result.get("confidence"),
            "missing_information": result.get("missing_information", []),
            "unverified_quotes": intake.get("unverified_quotes", []),
        },
        "recommendation": assessment["recommendation"] if assessment else None,
        "policy_id": state.get("policy_id"),
        "draft": draft,
        "allowed_actions": ["approve", "edit", "reject"] if draft else ["edit", "reject"],
    }
    if assessment:
        a = assessment["assessment"]
        packet["summary"] = a["summary"]
        packet["guardrail_notes"] = assessment["guardrail_notes"]
        packet["pathways"] = [
            {
                "name": p["name"],
                "cite": f"{p['policy_id']} section {p['section']}",
                "status": criteria.pathway_status(criteria.Pathway.model_validate(p)),
                "requirements": [
                    {"requirement": r["requirement"], "status": r["status"],
                     "quotes": [e["source_quote"] for e in r["evidence"]]}
                    for r in p["requirements"]
                ],
            }
            for p in a["pathways"]
        ]
        packet["exclusions_triggered"] = a["exclusions_triggered"]
        packet["general_requirements"] = [
            {"requirement": r["requirement"], "status": r["status"]} for r in a["general_requirements"]
        ]
    return packet


def validate_review(state_values: dict, decision: dict) -> ReviewDecision:
    """Check a reviewer decision against the case before resuming. Raises ValueError if invalid."""
    review = ReviewDecision.model_validate(decision)
    if review.action == "approve" and not state_values.get("draft"):
        raise ValueError("Nothing to approve: this case was escalated without a draft. Use 'edit' or 'reject'.")
    return review


def build_graph(deps: Deps, checkpointer):
    intake_fn = deps.intake_fn or (lambda text: run_intake(text, client=deps.llm_client, model=deps.model))

    def intake_node(state: CaseState):
        resp = intake_fn(state["note_text"])
        return {
            "intake": resp.model_dump(),
            "trace": [_event("intake", resp.latency_ms, resp.input_tokens, resp.output_tokens,
                             confidence=resp.result.confidence, unverified_quotes=len(resp.unverified_quotes))],
        }

    def policy_node(state: CaseState):
        intake = IntakeResult.model_validate(state["intake"]["result"])
        policy_id, chunks = deps.retrieve_policy(intake)
        return {
            "policy_id": policy_id,
            "policy_chunks": chunks,
            "trace": [_event("policy", policy_id=policy_id, chunks=len(chunks))],
        }

    def assess_node(state: CaseState):
        intake = IntakeResult.model_validate(state["intake"]["result"])
        result, call = criteria.assess(
            state["note_text"], intake, state["policy_chunks"], state["request_date"],
            client=deps.llm_client, model=deps.model,
        )
        return {
            "assessment": result.model_dump(),
            "trace": [_event("assess", call.latency_ms, call.input_tokens, call.output_tokens,
                             recommendation=result.recommendation, guardrail_notes=len(result.guardrail_notes))],
        }

    def draft_node(state: CaseState):
        intake = IntakeResult.model_validate(state["intake"]["result"])
        result = criteria.AssessmentResult.model_validate(state["assessment"])
        kind = drafter.KIND_BY_RECOMMENDATION[result.recommendation]
        policy_text = criteria.format_policy_context(state["policy_chunks"])
        d, call = drafter.draft(
            kind, intake, criteria.summarize_for_draft(result), policy_text,
            client=deps.llm_client, model=deps.model,
        )
        return {
            "draft": d.model_dump(),
            "trace": [_event("draft", call.latency_ms, call.input_tokens, call.output_tokens,
                             kind=kind, warnings=len(d.warnings))],
        }

    def escalate_node(state: CaseState):
        reason = escalation_reason(state) or "Escalated for human review."
        return {"escalation_reason": reason, "trace": [_event("escalate", reason=reason)]}

    def human_review_node(state: CaseState):
        # Nothing with side effects may run before interrupt(): on resume this node starts again.
        decision = interrupt(build_packet(state))
        return {"review": decision, "trace": [_event("human_review", action=decision.get("action"),
                                                    reviewer=decision.get("reviewer"))]}

    def finalize_node(state: CaseState):
        review = ReviewDecision.model_validate(state["review"])
        if review.action == "approve":
            status, document = "approved", state["draft"]["body"]
        elif review.action == "edit":
            status, document = "approved_with_edits", review.edited_letter
        else:
            status, document = "rejected", None
        return {"status": status, "final_document": document, "trace": [_event("finalize", status=status)]}

    def route_after_intake(state: CaseState) -> str:
        return "escalate" if escalation_reason(state) else "policy"

    def route_after_policy(state: CaseState) -> str:
        return "escalate" if escalation_reason(state) else "assess"

    def route_after_assess(state: CaseState) -> str:
        return "escalate" if escalation_reason(state) else "draft"

    g = StateGraph(CaseState)
    for name, fn in [("intake", intake_node), ("policy", policy_node), ("assess", assess_node),
                     ("draft", draft_node), ("escalate", escalate_node),
                     ("human_review", human_review_node), ("finalize", finalize_node)]:
        g.add_node(name, fn)
    g.add_edge(START, "intake")
    g.add_conditional_edges("intake", route_after_intake, {"policy": "policy", "escalate": "escalate"})
    g.add_conditional_edges("policy", route_after_policy, {"assess": "assess", "escalate": "escalate"})
    g.add_conditional_edges("assess", route_after_assess, {"draft": "draft", "escalate": "escalate"})
    g.add_edge("draft", "human_review")
    g.add_edge("escalate", "human_review")
    g.add_edge("human_review", "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer)


# ---- helpers that hide LangGraph's config plumbing from the API and the CLI ----

def _config(case_id: str) -> dict:
    return {"configurable": {"thread_id": case_id}}


def case_view(graph, case_id: str) -> Optional[dict]:
    snap = graph.get_state(_config(case_id))
    values = snap.values
    if not values:
        return None
    awaiting = "human_review" in (snap.next or ())
    return {
        "case_id": case_id,
        "status": "awaiting_review" if awaiting else values.get("status", "in_progress"),
        "recommendation": (values.get("assessment") or {}).get("recommendation"),
        "packet": build_packet(values) if awaiting else None,
        "review": values.get("review"),
        "final_document": values.get("final_document"),
        "trace": values.get("trace", []),
        "state": values,
    }


def start_case(graph, note_text: str, source_name: Optional[str] = None, request_date: Optional[str] = None) -> dict:
    case_id = uuid.uuid4().hex[:12]
    graph.invoke(
        {
            "case_id": case_id,
            "source_name": source_name,
            "note_text": note_text,
            "request_date": request_date or date.today().isoformat(),
            "trace": [],
        },
        _config(case_id),
    )
    return case_view(graph, case_id)


def resume_case(graph, case_id: str, decision: dict) -> dict:
    view = case_view(graph, case_id)
    if view is None:
        raise KeyError(case_id)
    if view["status"] != "awaiting_review":
        raise NotAwaitingReview(f"Case {case_id} is not awaiting review (status: {view['status']})")
    review = validate_review(view["state"], decision)
    graph.invoke(Command(resume=review.model_dump()), _config(case_id))
    return case_view(graph, case_id)
