"""SQLAlchemy ORM models for the application database (chat history, documents, etc.)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import (
    Boolean,
    Date,
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
    __table_args__ = (
        Index(
            "uq_rag_collections_owner_display_name",
            "owner_id",
            "display_name",
            unique=True,
        ),
    )

    name: Mapped[str] = mapped_column(String(63), primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class RagContainerFile(Base):
    """Uploaded document membership and durable indexing state for one RAG container."""

    __tablename__ = "rag_container_files"
    __table_args__ = (
        UniqueConstraint("collection_name", "relative_path", name="uq_rag_container_file_path"),
        Index("ix_rag_container_files_status_available", "status", "available_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generate_uuid)
    collection_name: Mapped[str] = mapped_column(
        String(63), ForeignKey("rag_collections.name", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    indexed_document_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    relative_path: Mapped[str] = mapped_column(String(1024))
    sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="staged", server_default="staged")
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    available_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class SqlConnection(Base):
    """Account owner for process-local SQL connections registered through the API."""

    __tablename__ = "sql_connections"

    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class AgentConfiguration(Base):
    """Installation-wide prompt overrides and custom agent profiles."""

    __tablename__ = "agent_configurations"

    name: Mapped[str] = mapped_column(String(63), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100))
    target: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(String(500))
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_agent: Mapped[str | None] = mapped_column(String(63), nullable=True)
    manifest_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


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


class MemoryVectorCleanupJob(Base):
    """Durable Qdrant deletion job that survives its source conversation."""

    __tablename__ = "memory_vector_cleanup_jobs"
    __table_args__ = (Index("ix_memory_cleanup_status_available", "status", "available_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generate_uuid)
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="RESTRICT"), index=True
    )
    conversation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    available_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class ActionItem(Base):
    """A private task in an account's project planner."""

    __tablename__ = "action_items"
    __table_args__ = (Index("ix_action_items_owner_status_due", "owner_id", "status", "due_date"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generate_uuid)
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="RESTRICT"), index=True
    )
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="next", server_default="next")
    priority: Mapped[str] = mapped_column(String(16), default="normal", server_default="normal")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_repository_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class GitHubConnection(Base):
    """Encrypted per-account GitHub App user authorization."""

    __tablename__ = "github_connections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generate_uuid)
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), unique=True, index=True
    )
    github_user_id: Mapped[str] = mapped_column(String(32))
    github_login: Mapped[str] = mapped_column(String(128))
    encrypted_access_token: Mapped[str] = mapped_column(Text)
    encrypted_refresh_token: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    refresh_expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class GitHubRepositorySelection(Base):
    """A repository explicitly made available to one account's GitHub agent."""

    __tablename__ = "github_repository_selections"
    __table_args__ = (UniqueConstraint("owner_id", "repository_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generate_uuid)
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    repository_id: Mapped[str] = mapped_column(String(32))
    full_name: Mapped[str] = mapped_column(String(256))
    html_url: Mapped[str] = mapped_column(String(512))
    default_branch: Mapped[str] = mapped_column(String(256))
    is_private: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class GitHubOAuthState(Base):
    """One-time OAuth state bound to the initiating account session."""

    __tablename__ = "github_oauth_states"

    state_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("account_sessions.id", ondelete="CASCADE"), index=True
    )
    browser_binding_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


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
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    storage_path: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class ResumeRaterWorkspace(Base):
    """Private hiring workspace for one job posting and its candidate pool."""

    __tablename__ = "resume_rater_workspaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generate_uuid)
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    current_revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class ResumeRaterRevision(Base):
    """Immutable job posting and approved scoring rubric revision."""

    __tablename__ = "resume_rater_revisions"
    __table_args__ = (
        UniqueConstraint("workspace_id", "version", name="uq_resume_rater_revision_version"),
        Index("ix_resume_rater_revisions_workspace_status", "workspace_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generate_uuid)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("resume_rater_workspaces.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    job_posting: Mapped[str] = mapped_column(Text)
    criteria_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24), index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class ResumeRaterCandidate(Base):
    """One candidate and the private resume file supplied for a workspace."""

    __tablename__ = "resume_rater_candidates"
    __table_args__ = (
        UniqueConstraint("workspace_id", "content_sha256", name="uq_resume_rater_candidate_file"),
        Index("ix_resume_rater_candidates_workspace", "workspace_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generate_uuid)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("resume_rater_workspaces.id", ondelete="CASCADE"), index=True
    )
    display_name: Mapped[str] = mapped_column(String(255))
    filename: Mapped[str] = mapped_column(String(255))
    resume_path: Mapped[str] = mapped_column(String(1_024))
    content_sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class ResumeRaterAssessment(Base):
    """Versioned, reviewable result for one candidate and one rubric revision."""

    __tablename__ = "resume_rater_assessments"
    __table_args__ = (
        UniqueConstraint("candidate_id", "revision_id", name="uq_resume_rater_assessment_version"),
        Index("ix_resume_rater_assessments_revision_status", "revision_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generate_uuid)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("resume_rater_workspaces.id", ondelete="CASCADE"), index=True
    )
    candidate_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("resume_rater_candidates.id", ondelete="CASCADE"), index=True
    )
    revision_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("resume_rater_revisions.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ResumeRaterTask(Base):
    """Durable queue item for drafting a rubric or rating one resume."""

    __tablename__ = "resume_rater_tasks"
    __table_args__ = (
        Index("ix_resume_rater_tasks_status_created", "status", "created_at"),
        Index("ix_resume_rater_tasks_workspace", "workspace_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generate_uuid)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("resume_rater_workspaces.id", ondelete="CASCADE"), index=True
    )
    revision_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("resume_rater_revisions.id", ondelete="CASCADE"), index=True
    )
    assessment_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("resume_rater_assessments.id", ondelete="CASCADE"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    lease_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class RedactionJob(Base):
    """Account-owned review state for a local document redaction run."""

    __tablename__ = "redaction_jobs"
    __table_args__ = (Index("ix_redaction_jobs_status_created", "status", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_generate_uuid)
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("accounts.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    instructions: Mapped[str] = mapped_column(String(2_000), default="")
    categories_json: Mapped[str] = mapped_column(Text)
    source_sha256: Mapped[str] = mapped_column(String(64))
    job_dir: Mapped[str] = mapped_column(String(1_024))
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    pages_processed: Mapped[int] = mapped_column(Integer, default=0)
    review_revision: Mapped[int] = mapped_column(Integer, default=0)
    approved_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    clarification_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    clarification_answers: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
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
