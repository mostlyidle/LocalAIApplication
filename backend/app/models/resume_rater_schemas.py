"""Validated API and model output schemas for resume rating."""

from __future__ import annotations

import re
from datetime import datetime  # noqa: TC003 - Pydantic resolves this annotation at runtime.
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

MIN_RESUME_RUBRIC_CRITERIA = 3
MAX_RESUME_RUBRIC_CRITERIA = 8


class ResumeRaterWorkspaceCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    job_posting: str = Field(min_length=100, max_length=32_000)

    @field_validator("title", "job_posting")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        result = value.strip()
        if not result:
            raise ValueError("This field cannot be blank.")
        return result


class ResumeRaterRevisionCreate(BaseModel):
    job_posting: str = Field(min_length=100, max_length=32_000)

    @field_validator("job_posting")
    @classmethod
    def strip_posting(cls, value: str) -> str:
        result = value.strip()
        if not result:
            raise ValueError("Paste the complete job posting.")
        return result


class ResumeRubricCriterion(BaseModel):
    id: str = Field(min_length=1, max_length=40, pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=2, max_length=120)
    description: str = Field(min_length=4, max_length=500)
    weight: int = Field(ge=1, le=100)
    must_have: bool = False


class ResumeRubric(BaseModel):
    criteria: list[ResumeRubricCriterion] = Field(
        min_length=MIN_RESUME_RUBRIC_CRITERIA,
        max_length=MAX_RESUME_RUBRIC_CRITERIA,
    )

    @model_validator(mode="after")
    def validate_rubric(self) -> ResumeRubric:
        identifiers = [criterion.id for criterion in self.criteria]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Rubric criterion IDs must be unique.")
        if sum(criterion.weight for criterion in self.criteria) != 100:
            raise ValueError("Rubric weights must add up to 100.")
        return self


class ResumeRaterRubricUpdate(ResumeRubric):
    pass


class ResumeRaterCandidateNameUpdate(BaseModel):
    display_name: str = Field(min_length=1, max_length=255)

    @field_validator("display_name")
    @classmethod
    def strip_display_name(cls, value: str) -> str:
        result = value.strip()
        if not result:
            raise ValueError("Candidate name cannot be blank.")
        return result


class ResumeRaterWorkspaceResponse(BaseModel):
    id: str
    title: str
    current_revision: int
    revision_status: str
    candidate_count: int
    created_at: datetime
    updated_at: datetime


class ResumeRaterRevisionResponse(BaseModel):
    id: str
    version: int
    job_posting: str
    criteria: list[ResumeRubricCriterion] | None
    status: str
    error_message: str | None
    created_at: datetime


ResumeRaterEvidenceLevel = Literal[
    "not_demonstrated", "weak", "partial", "substantial", "fully_meets"
]


class ResumeRaterEvidenceScore(BaseModel):
    criterion_id: str
    level: ResumeRaterEvidenceLevel = Field(
        description=(
            "Use not_demonstrated only when no resume evidence supports the criterion; "
            "that level requires an empty evidence_quotes list."
        )
    )
    explanation: str = Field(min_length=1, max_length=500)
    evidence_quotes: list[str] = Field(
        max_length=4,
        description=(
            "Use an empty list for not_demonstrated. For every other level, include one to "
            "four exact, verbatim quotes from the resume."
        ),
    )

    @model_validator(mode="after")
    def validate_evidence_for_level(self) -> ResumeRaterEvidenceScore:
        if self.level == "not_demonstrated" and self.evidence_quotes:
            raise ValueError("A criterion marked not demonstrated cannot include evidence quotes.")
        if self.level != "not_demonstrated" and not self.evidence_quotes:
            raise ValueError("A demonstrated criterion must include resume evidence.")
        return self


class ResumeRaterPoint(BaseModel):
    criterion_id: str
    text: str = Field(min_length=1, max_length=500)
    evidence_quotes: list[str] = Field(min_length=1, max_length=4)


class ResumeRaterSuggestion(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    source_quote: str = Field(min_length=1, max_length=600)


class ResumeRaterModelSuggestion(BaseModel):
    focus: Literal[
        "clarify_scope",
        "add_context",
        "quantify_impact",
        "use_action_verb",
        "connect_to_job",
    ]
    source_quote: str = Field(min_length=1, max_length=600)


class ResumeRaterReport(BaseModel):
    summary: str = Field(min_length=1, max_length=1_000)
    criterion_scores: list[ResumeRaterEvidenceScore] = Field(min_length=3, max_length=8)
    strengths: list[ResumeRaterPoint] = Field(default_factory=list, max_length=8)
    gaps: list[ResumeRaterPoint] = Field(default_factory=list, max_length=8)
    interview_questions: list[str] = Field(default_factory=list, max_length=8)
    resume_suggestions: list[ResumeRaterSuggestion] = Field(default_factory=list, max_length=8)


class ResumeRaterAssessmentResponse(BaseModel):
    id: str
    revision_version: int
    status: str
    score: int | None
    rank: int | None = None
    must_haves_not_met: list[str] = Field(default_factory=list)
    result: ResumeRaterReport | None
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None


class ResumeRaterCandidateResponse(BaseModel):
    id: str
    display_name: str
    filename: str
    created_at: datetime
    current_assessment: ResumeRaterAssessmentResponse | None
    history: list[ResumeRaterAssessmentResponse]


class ResumeRaterWorkspaceDetail(ResumeRaterWorkspaceResponse):
    revisions: list[ResumeRaterRevisionResponse]
    candidates: list[ResumeRaterCandidateResponse]


class ResumeRaterCancelResponse(BaseModel):
    status: Literal["cancelled"]


class ResumeRaterDeleteResponse(BaseModel):
    status: Literal["deleted"]


class ResumeRaterModelRubricCriterion(ResumeRubricCriterion):
    """Model-produced relative weight, before scaling to the final 100-point rubric."""

    weight: int = Field(ge=1, le=10_000)


class ResumeRaterModelRubric(BaseModel):
    """Structured rubric returned by the local model before weight normalization."""

    criteria: list[ResumeRaterModelRubricCriterion] = Field(
        min_length=MIN_RESUME_RUBRIC_CRITERIA,
        max_length=MAX_RESUME_RUBRIC_CRITERIA,
    )


class ResumeRaterModelEvidenceScore(BaseModel):
    """Model evidence score before application-level conditional validation."""

    criterion_id: str
    level: ResumeRaterEvidenceLevel = Field(
        description=(
            "Use not_demonstrated only when no resume evidence supports the criterion; "
            "that level requires an empty evidence_quotes list."
        )
    )
    explanation: str = Field(min_length=1, max_length=500)
    evidence_quotes: list[str] = Field(
        max_length=4,
        description=(
            "Use an empty list for not_demonstrated. For every other level, include one to "
            "four exact, verbatim quotes from the resume."
        ),
    )


class ResumeRaterModelReport(BaseModel):
    """Structured report returned by the local model before evidence checks."""

    summary: str = Field(min_length=1, max_length=1_000)
    criterion_scores: list[ResumeRaterModelEvidenceScore] = Field(min_length=3, max_length=8)
    strengths: list[ResumeRaterPoint] = Field(default_factory=list, max_length=8)
    gaps: list[ResumeRaterPoint] = Field(default_factory=list, max_length=8)
    interview_questions: list[str] = Field(default_factory=list, max_length=8)
    resume_suggestions: list[ResumeRaterModelSuggestion] = Field(default_factory=list, max_length=8)


def candidate_label(filename: str) -> str:
    """Create a readable manager-editable label without trusting path components."""
    stem = re.sub(r"\s+", " ", filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]).strip()
    stem = re.sub(r"\.(pdf|docx)$", "", stem, flags=re.IGNORECASE).strip(" .")
    return (stem or "Candidate")[:255]
