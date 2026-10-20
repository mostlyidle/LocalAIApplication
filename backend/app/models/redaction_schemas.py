"""Request and response schemas for document redaction jobs."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.services.redaction_detector import DEFAULT_CATEGORIES


class RedactionPolicy(BaseModel):
    """Shared redaction choices applied to one or more documents."""

    categories: list[str] = Field(default_factory=lambda: list(DEFAULT_CATEGORIES), max_length=20)
    instructions: str = Field(default="", max_length=2_000)

    @field_validator("categories")
    @classmethod
    def validate_categories(cls, values: list[str]) -> list[str]:
        normalized = list(
            dict.fromkeys(value.strip().casefold() for value in values if value.strip())
        )
        if not normalized:
            raise ValueError("Choose at least one redaction category.")
        if any(len(value) > 100 for value in normalized):
            raise ValueError("Redaction category labels must be at most 100 characters.")
        return normalized


class RedactionJobCreate(RedactionPolicy):
    document_id: str = Field(min_length=36, max_length=36)


class RedactionBatchCreate(RedactionPolicy):
    """Create one queued redaction job for each selected source document."""

    document_ids: list[str] = Field(min_length=1, max_length=20)

    @field_validator("document_ids")
    @classmethod
    def validate_document_ids(cls, values: list[str]) -> list[str]:
        try:
            normalized = [str(UUID(value)) for value in values]
        except ValueError as exc:
            raise ValueError("Document IDs must be valid UUIDs.") from exc
        if len(set(normalized)) != len(normalized):
            raise ValueError("A document can only appear once in a batch.")
        return normalized


class RedactionClarification(BaseModel):
    answer: str = Field(min_length=1, max_length=1_000)

    @field_validator("answer")
    @classmethod
    def validate_answer(cls, value: str) -> str:
        answer = value.strip()
        if not answer:
            raise ValueError("Enter a clarification before continuing.")
        return answer


class RedactionJobResponse(BaseModel):
    id: str
    document_id: str
    batch_id: str | None = None
    status: str
    page_count: int
    pages_processed: int
    review_revision: int
    approved_revision: int | None
    error_message: str | None
    clarification_question: str | None = None
    warnings: list[str] = Field(default_factory=list)


class RedactionBatchResponse(BaseModel):
    """A batch identifier and its independently reviewable redaction jobs."""

    id: str
    jobs: list[RedactionJobResponse]


class RedactionFinding(BaseModel):
    id: str
    page_number: int
    category: str
    text: str
    confidence: float | None
    source: str
    selected: bool
    boxes: list[list[float]]


class RedactionPageSummary(BaseModel):
    number: int
    width: float
    height: float


class RedactionFailedPage(BaseModel):
    """A page whose extraction failed and may need recovery."""

    page_number: int
    error: str
    manual_reviewed: bool
    attempts: int
    whole_page_redacted: bool = False


class RedactionReviewResponse(BaseModel):
    job: RedactionJobResponse
    findings: list[RedactionFinding]
    pages: list[RedactionPageSummary]
    failed_pages: list[RedactionFailedPage] = Field(default_factory=list)


class RedactionFindingUpdate(BaseModel):
    selected: bool
    boxes: list[list[float]] = Field(min_length=1, max_length=100)


class RedactionManualBox(BaseModel):
    page_number: int = Field(ge=0)
    box: list[float] = Field(min_length=4, max_length=4)


class RedactionPageAction(BaseModel):
    """Identify the document page targeted by a recovery action."""

    page_number: int = Field(ge=0)
