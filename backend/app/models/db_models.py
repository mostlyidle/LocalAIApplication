"""SQLAlchemy ORM models for the application database (chat history, documents, etc.)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


def _generate_uuid() -> str:
    return str(uuid.uuid4())


LEGACY_ACCOUNT_ID = "00000000-0000-4000-8000-000000000000"


class Account(Base):
    """A sign-in identity and owner of private application data."""

    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generate_uuid)
    username: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128))
    password_hash: Mapped[str] = mapped_column(String(255))
    is_enabled: Mapped[bool] = mapped_column(default=True)
    memory_enabled: Mapped[bool] = mapped_column(default=False)
    past_chat_recall_enabled: Mapped[bool] = mapped_column(default=False)
    memory_epoch: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class AccountSession(Base):
    """A revocable session with a digested cookie token and bound CSRF token."""

    __tablename__ = "account_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generate_uuid)
    account_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class MeetingStreamTicket(Base):
    """Native meeting WebSocket capability bound to one login and meeting."""

    __tablename__ = "meeting_stream_tickets"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("account_sessions.id", ondelete="CASCADE"), index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class RagCollection(Base):
    """Private ownership registry for application-managed vector collections."""

    __tablename__ = "rag_collections"

    name: Mapped[str] = mapped_column(String(63), primary_key=True)
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class SqlConnection(Base):
    """Account owner for process-local SQL connections registered through the API."""

    __tablename__ = "sql_connections"

    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class Conversation(Base):
    """A chat conversation containing multiple messages."""

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generate_uuid)
    owner_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), default="New Conversation")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    exclude_from_memory: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false()
    )
    summary_through_message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    summary_message_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    summary_revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    messages: Mapped[list[Message]] = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by=lambda: (Message.created_at, Message.id),
    )


class Message(Base):
    """A single message within a conversation."""

    __tablename__ = "messages"
    __table_args__ = (
        Index(
            "uq_messages_conversation_client_turn_role",
            "conversation_id",
            "client_turn_id",
            "role",
            unique=True,
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generate_uuid)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))  # user | assistant | system | tool
    content: Mapped[str] = mapped_column(Text)
    client_turn_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    turn_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    agent_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    execution_metadata: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    conversation: Mapped[Conversation] = relationship("Conversation", back_populates="messages")
    tool_calls: Mapped[list[ToolCallRecord]] = relationship(
        "ToolCallRecord",
        back_populates="message",
        cascade="all, delete-orphan",
    )


class Memory(Base):
    """An explicitly approved, account-owned fact or preference."""

    __tablename__ = "memories"
    __table_args__ = (
        Index("ix_memories_owner_deleted", "owner_id", "deleted_at"),
        Index("ix_memories_owner_kind", "owner_id", "kind"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generate_uuid)
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="RESTRICT"), index=True
    )
    kind: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text)
    project_scope: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_conversation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    origin_agent: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approved: Mapped[bool] = mapped_column(default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class MemoryOutboxJob(Base):
    """Durable, idempotent work item for indexing one eligible chat turn."""

    __tablename__ = "memory_outbox_jobs"
    __table_args__ = (
        UniqueConstraint("source_message_id", name="uq_memory_outbox_source_message"),
        Index("ix_memory_outbox_status_available", "status", "available_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generate_uuid)
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="RESTRICT"), index=True
    )
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    source_message_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("messages.id", ondelete="CASCADE")
    )
    memory_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    available_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class ConversationRecallSummary(Base):
    """Bounded derived text for cross-conversation retrieval, scoped to its source chat."""

    __tablename__ = "conversation_recall_summaries"
    __table_args__ = (
        UniqueConstraint("conversation_id", name="uq_recall_summary_conversation"),
        Index("ix_recall_summaries_owner_epoch", "owner_id", "memory_epoch"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generate_uuid)
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="RESTRICT"), index=True
    )
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE")
    )
    source_message_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("messages.id", ondelete="CASCADE")
    )
    memory_epoch: Mapped[int] = mapped_column(Integer, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    content: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class ToolCallRecord(Base):
    """Record of a tool invocation made during message generation."""

    __tablename__ = "tool_calls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generate_uuid)
    message_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("messages.id", ondelete="CASCADE"), index=True
    )
    tool_name: Mapped[str] = mapped_column(String(100))
    tool_input: Mapped[str] = mapped_column(Text)  # JSON-serialized
    tool_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    message: Mapped[Message] = relationship("Message", back_populates="tool_calls")


class Document(Base):
    """Metadata for an uploaded document."""

    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generate_uuid)
    owner_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(255))
    format: Mapped[str] = mapped_column(String(20))
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_path: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class Meeting(Base):
    """Metadata and lifecycle state for a consented audio meeting.

    Audio is deliberately not represented by this model. Audio frames are
    accepted by the protocol only long enough to validate their sequence and
    are handed to the local ASR boundary without being persisted. A meeting
    starts in ``created`` and only the authoritative stream start changes it
    to ``active``.
    """

    __tablename__ = "meetings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generate_uuid)
    owner_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("accounts.id", ondelete="RESTRICT"),
        index=True,
    )
    status: Mapped[str] = mapped_column(String(20), default="created", index=True)
    consent_policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    consent_attested_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_transcript_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    transcript_segments: Mapped[list[TranscriptSegment]] = relationship(
        "TranscriptSegment",
        back_populates="meeting",
        cascade="all, delete-orphan",
        order_by="TranscriptSegment.sequence",
    )
    detected_questions: Mapped[list[DetectedQuestion]] = relationship(
        "DetectedQuestion",
        back_populates="meeting",
        cascade="all, delete-orphan",
        order_by="DetectedQuestion.created_at",
    )


class TranscriptSegment(Base):
    """A local ASR transcript segment belonging to a meeting."""

    __tablename__ = "transcript_segments"
    __table_args__ = (
        UniqueConstraint("meeting_id", "sequence", name="uq_transcript_meeting_sequence"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generate_uuid)
    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    speaker: Mapped[str | None] = mapped_column(String(100), nullable=True)
    text: Mapped[str] = mapped_column(Text, default="")
    start_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    meeting: Mapped[Meeting] = relationship("Meeting", back_populates="transcript_segments")
    detected_questions: Mapped[list[DetectedQuestion]] = relationship(
        "DetectedQuestion", back_populates="transcript_segment"
    )


class DetectedQuestion(Base):
    """A question detected from a meeting transcript in a later phase."""

    __tablename__ = "detected_questions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generate_uuid)
    meeting_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("meetings.id", ondelete="CASCADE"), index=True
    )
    transcript_segment_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("transcript_segments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    question: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))

    meeting: Mapped[Meeting] = relationship("Meeting", back_populates="detected_questions")
    transcript_segment: Mapped[TranscriptSegment | None] = relationship(
        "TranscriptSegment", back_populates="detected_questions"
    )
