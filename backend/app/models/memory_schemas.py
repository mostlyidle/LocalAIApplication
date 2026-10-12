"""Schemas for explicit, user-approved memories."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MemoryKind = Literal["preference", "fact", "project_decision"]


class MemoryCreate(BaseModel):
    """A fact the signed-in user explicitly chose to remember."""

    kind: MemoryKind = "fact"
    content: str = Field(min_length=1, max_length=4_000)
    project_scope: str | None = Field(default=None, max_length=128)
    source_conversation_id: str | None = Field(default=None, min_length=1, max_length=36)
    source_message_id: str | None = Field(default=None, min_length=1, max_length=36)
    source_client_turn_id: str | None = Field(default=None, min_length=1, max_length=36)
    origin_agent: str | None = Field(default=None, max_length=64)

    @field_validator("content")
    @classmethod
    def nonblank_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Memory content cannot be blank.")
        return value

    @model_validator(mode="after")
    def prevent_duplicate_source_ids(self) -> MemoryCreate:
        if self.source_message_id and self.source_client_turn_id:
            raise ValueError("Provide a source message ID or client turn ID, not both.")
        return self


class MemoryUpdate(BaseModel):
    """Revision-checked correction to an existing memory."""

    revision: int = Field(ge=1)
    content: str | None = Field(default=None, min_length=1, max_length=4_000)
    kind: MemoryKind | None = None
    project_scope: str | None = Field(default=None, max_length=128)

    @field_validator("content")
    @classmethod
    def nonblank_content(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("Memory content cannot be blank.")
        return value

    @model_validator(mode="after")
    def require_a_change(self) -> MemoryUpdate:
        if self.content is None and self.kind is None and self.project_scope is None:
            raise ValueError("At least one memory field must be updated.")
        return self


class MemorySettingsUpdate(BaseModel):
    """Independent account-level memory controls."""

    memory_enabled: bool | None = None
    past_chat_recall_enabled: bool | None = None

    @model_validator(mode="after")
    def require_a_setting(self) -> MemorySettingsUpdate:
        if self.memory_enabled is None and self.past_chat_recall_enabled is None:
            raise ValueError("At least one setting must be supplied.")
        return self


class ConversationMemorySettingsUpdate(BaseModel):
    """Conversation-specific opt-out from future cross-chat memory use."""

    exclude_from_memory: bool


class MemoryResponse(BaseModel):
    """Memory fields safe to return to its owning account."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    kind: MemoryKind
    content: str
    project_scope: str | None
    source_conversation_id: str | None
    source_message_id: str | None
    origin_agent: str | None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None
    revision: int


class MemoryListResponse(BaseModel):
    """Page of active memories."""

    memories: list[MemoryResponse]
    total: int
    limit: int
    offset: int


class MemorySettingsResponse(BaseModel):
    """Current account-level memory controls."""

    memory_enabled: bool
    past_chat_recall_enabled: bool


class MemoryDeleteAllResponse(BaseModel):
    """Result of invalidating all current memories."""

    deleted_count: int
    memory_epoch: int
    past_chat_recall_enabled: bool
