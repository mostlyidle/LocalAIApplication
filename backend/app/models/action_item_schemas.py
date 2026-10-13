"""Request and response schemas for the account-owned project planner."""

from __future__ import annotations

from datetime import date, datetime  # noqa: TC003 - Pydantic resolves these at runtime.
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ActionStatus = Literal["next", "in_progress", "done"]
ActionPriority = Literal["low", "normal", "high"]
ActionSource = Literal["chat", "meeting", "document", "github"]


class ActionItemCreate(BaseModel):
    """An action item explicitly added to the planner."""

    title: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=4_000)
    status: ActionStatus = "next"
    priority: ActionPriority = "normal"
    due_date: date | None = None
    source_type: ActionSource | None = None
    source_id: str | None = Field(default=None, min_length=1, max_length=36)
    source_repository_id: str | None = Field(default=None, min_length=1, max_length=32)
    source_quote: str | None = Field(default=None, min_length=1, max_length=500)

    @field_validator("title")
    @classmethod
    def nonblank_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Title cannot be blank.")
        return value

    @model_validator(mode="after")
    def source_fields_match(self) -> ActionItemCreate:
        if (self.source_type is None) != (self.source_id is None):
            raise ValueError("source_type and source_id must be supplied together.")
        if self.source_quote is not None and self.source_id is None:
            raise ValueError("A source quote requires a source record.")
        if self.source_type == "github" and self.source_repository_id is None:
            raise ValueError("GitHub source items require a selected repository.")
        if self.source_type != "github" and self.source_repository_id is not None:
            raise ValueError("A repository is only valid for a GitHub source.")
        return self


class ActionItemUpdate(BaseModel):
    """Revision-checked update to an action item."""

    revision: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=4_000)
    status: ActionStatus | None = None
    priority: ActionPriority | None = None
    due_date: date | None = None

    @field_validator("title")
    @classmethod
    def nonblank_title(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("Title cannot be blank.")
        return value

    @model_validator(mode="after")
    def require_change(self) -> ActionItemUpdate:
        if not self.model_fields_set - {"revision"}:
            raise ValueError("At least one action item field must be updated.")
        return self


class ActionItemResponse(BaseModel):
    """Action item fields visible to its owning account."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: str | None
    status: ActionStatus
    priority: ActionPriority
    due_date: date | None
    source_type: ActionSource | None
    source_id: str | None
    source_repository_id: str | None
    source_quote: str | None
    revision: int
    created_at: datetime
    updated_at: datetime


class ActionItemListResponse(BaseModel):
    items: list[ActionItemResponse]
    total: int


class ProposalSourceRequest(BaseModel):
    """Identify one owned chat, meeting, or document to review for next steps."""

    source_type: Literal["chat", "meeting", "document"]
    source_id: str = Field(min_length=1, max_length=36)


class ActionItemSuggestion(BaseModel):
    """A candidate action item with a verbatim source quote."""

    title: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=1_000)
    priority: ActionPriority = "normal"
    due_date: date | None = None
    source_quote: str = Field(min_length=1, max_length=500)


class ActionItemProposalResponse(BaseModel):
    """Suggestions are returned for user review and are not saved automatically."""

    source_type: Literal["chat", "meeting", "document"]
    source_id: str
    source_title: str
    suggestions: list[ActionItemSuggestion]

