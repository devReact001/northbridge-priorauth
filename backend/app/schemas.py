from typing import Optional

from pydantic import BaseModel, Field, field_validator


class Evidence(BaseModel):
    """A single clinical fact plus the exact text it was taken from."""

    finding: str = Field(description="Short clinical finding, e.g. 'Failed 8 weeks of physical therapy'")
    source_quote: str = Field(description="Verbatim quote from the note supporting the finding")


class IntakeResult(BaseModel):
    """Structured output of the intake agent. Every field must come from the note;
    use null / empty list when the note does not say."""

    patient_ref: Optional[str] = Field(None, description="Patient identifier as written in the note")
    age: Optional[int] = None
    sex: Optional[str] = None
    requested_procedure: Optional[str] = Field(None, description="Procedure or service being requested")
    procedure_code: Optional[str] = Field(None, description="CPT/HCPCS code if stated in the note, else null")
    diagnoses: list[str] = Field(default_factory=list)
    diagnosis_codes: list[str] = Field(default_factory=list, description="ICD-10 codes only if stated")
    prior_treatments: list[Evidence] = Field(default_factory=list)
    supporting_evidence: list[Evidence] = Field(default_factory=list)
    pertinent_negatives: list[Evidence] = Field(
        default_factory=list,
        description="Findings the note explicitly denies (e.g. 'No history of cancer'), with verbatim quote",
    )
    missing_information: list[str] = Field(
        default_factory=list,
        description="Things a prior-auth reviewer would normally need that the note does not contain",
    )
    confidence: float = Field(ge=0, le=1, description="Overall extraction confidence, 0 to 1")

    @field_validator("patient_ref", "sex", "requested_procedure", "procedure_code", mode="before")
    @classmethod
    def empty_to_none(cls, v):
        """Models sometimes return "" instead of null. Downstream code must never see ""."""
        return None if isinstance(v, str) and not v.strip() else v


class IntakeRequest(BaseModel):
    text: str = Field(min_length=20)
    source_name: Optional[str] = None


class IntakeResponse(BaseModel):
    result: IntakeResult
    model: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    needs_human_review: bool
    unverified_quotes: list[str] = Field(
        default_factory=list,
        description="Quotes the model returned that do not appear in the source note",
    )