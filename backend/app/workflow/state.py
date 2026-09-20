import operator
from typing import Annotated, Literal, Optional, TypedDict

from pydantic import BaseModel, model_validator


class CaseState(TypedDict, total=False):
    """Everything the workflow knows about one case. Plain JSON-friendly values only, so the
    checkpointer can store it and the dashboard can read it."""

    case_id: str
    source_name: Optional[str]
    note_text: str
    request_date: str
    intake: dict  # IntakeResponse as a dict
    policy_id: Optional[str]
    policy_chunks: list[dict]
    ehr: dict  # EhrResult as a dict: facts pulled from the patient's chart through MCP tools
    assessment: dict  # AssessmentResult as a dict
    draft: dict  # DraftResult as a dict
    escalation_reason: Optional[str]
    review: dict  # the human reviewer's decision
    status: str
    final_document: Optional[str]
    dispatch: dict  # what was sent out after approval (or why nothing was)
    trace: Annotated[list[dict], operator.add]  # one event per node, appended, never overwritten


class ReviewDecision(BaseModel):
    """What a human reviewer sends back to resume a paused case."""

    action: Literal["approve", "edit", "reject"]
    reviewer: str
    notes: str = ""
    edited_letter: Optional[str] = None

    @model_validator(mode="after")
    def _check(self):
        if not self.reviewer.strip():
            raise ValueError("reviewer name is required")
        if self.action == "edit" and not (self.edited_letter or "").strip():
            raise ValueError("action 'edit' requires edited_letter")
        return self
