"""Intake agent: turns an unstructured clinical note into a structured IntakeResult.

Uses Claude tool-use with a forced tool call so the output is always schema-shaped JSON.
The Anthropic client is injectable so tests can run without network or an API key.
"""

import re
import time
from typing import Any, Optional

from ..config import settings
from ..schemas import IntakeResponse, IntakeResult

SYSTEM_PROMPT = """You are the intake step of a prior-authorization assistant for a hospital.
Extract structured facts from the clinical note using the record_intake tool.

Rules:
- Only record what the note explicitly states. Never infer diagnoses, codes, or dates.
- Every evidence item needs a verbatim quote copied exactly from the note.
- Use null (never an empty string) for unknown single-value fields, and [] for unknown lists.
- Record findings the note explicitly denies (for example "no history of cancer", "no fever")
  under pertinent_negatives, with a verbatim quote.
- Documentation limitations (for example "exam limited today") are NOT supporting evidence.
  List them under missing_information instead.
- missing_information must name only what the note itself lacks (for example imaging results,
  duration of conservative therapy). Do NOT state payer policy requirements or typical durations:
  a separate policy step handles that.
- Lower your confidence when the note is short, ambiguous, or contradictory.
- You assist human reviewers. You do not make coverage or clinical decisions."""

CONFIDENCE_REVIEW_THRESHOLD = 0.75

TOOL = {
    "name": "record_intake",
    "description": "Record the structured intake data extracted from the clinical note.",
    "input_schema": IntakeResult.model_json_schema(),
}


def _norm(s: str) -> str:
    """Collapse all whitespace (including line breaks) and lowercase, for quote matching."""
    return re.sub(r"\s+", " ", s).strip().lower()


def unverified_quotes(result: IntakeResult, text: str) -> list[str]:
    """Return every source_quote that does not literally appear in the note.

    Whitespace is normalised first, because notes often break a sentence across lines.
    """
    note = _norm(text)
    items = result.prior_treatments + result.supporting_evidence + result.pertinent_negatives
    return [e.source_quote for e in items if _norm(e.source_quote) not in note]


def _get_client():
    from anthropic import Anthropic

    return Anthropic(api_key=settings.anthropic_api_key)


def run_intake(text: str, client: Optional[Any] = None, model: Optional[str] = None) -> IntakeResponse:
    client = client or _get_client()
    model = model or settings.anthropic_model

    start = time.perf_counter()
    message = client.messages.create(
        model=model,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        tools=[TOOL],
        tool_choice={"type": "tool", "name": "record_intake"},
        messages=[{"role": "user", "content": f"<clinical_note>\n{text}\n</clinical_note>"}],
    )
    latency_ms = int((time.perf_counter() - start) * 1000)

    tool_block = next((b for b in message.content if getattr(b, "type", None) == "tool_use"), None)
    if tool_block is None:
        raise ValueError("Model did not return a record_intake tool call")

    result = IntakeResult.model_validate(tool_block.input)
    bad_quotes = unverified_quotes(result, text)

    # Human-in-the-loop rule: low confidence, gaps in the note, or any quote we
    # cannot find in the source text always go to a reviewer.
    needs_review = (
        result.confidence < CONFIDENCE_REVIEW_THRESHOLD
        or bool(result.missing_information)
        or bool(bad_quotes)
    )

    return IntakeResponse(
        result=result,
        model=model,
        latency_ms=latency_ms,
        input_tokens=message.usage.input_tokens,
        output_tokens=message.usage.output_tokens,
        needs_human_review=needs_review,
        unverified_quotes=bad_quotes,
    )