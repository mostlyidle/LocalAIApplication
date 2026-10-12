"""Pydantic request/response schemas for all API endpoints."""

from __future__ import annotations

import json
import struct
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator

from app.models.enums import (
    AgentType,
    AudioSource,
    DocumentFormat,
    DocumentStatus,
    MeetingStatus,
    MessageRole,
    StreamEventType,
)
from app.models.profile_schemas import InferenceOptions

# =============================================================================
# Chat
# =============================================================================


class ChatMessageRequest(BaseModel):
    """Incoming chat message from the user."""

    content: str = Field(..., min_length=1, max_length=32_000)
    conversation_id: str | None = None
    attachments: list[str] = Field(default_factory=list)
    agent_name: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,62}$")
    collection: str = Field(default="documents", pattern=r"^[A-Za-z0-9_-]{1,63}$")
    symbol: str | None = Field(default=None, pattern=r"^[A-Za-z0-9.^=-]{1,20}$")
    workspace_path: str | None = Field(default=None, max_length=500)
    context: str | None = Field(default=None, max_length=100_000)
    workflow: dict[str, Any] | None = None
    inference: InferenceOptions | None = None


class ToolCallInfo(BaseModel):
    """Metadata about a tool call made during agent execution."""

    tool_name: str
    tool_input: dict[str, Any]
    tool_output: str | None = None
    duration_ms: float | None = None


class ChatMessageResponse(BaseModel):
    """Response from the chat endpoint (non-streaming)."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    conversation_id: str
    role: MessageRole = MessageRole.ASSISTANT
    content: str
    agent_used: str | None = None
    tool_calls: list[ToolCallInfo] = Field(default_factory=list)
    execution: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class StreamEvent(BaseModel):
    """A single event in the WebSocket streaming protocol."""

    type: StreamEventType
    content: str | None = None
    tool: str | None = None
    input: dict[str, Any] | None = None
    output: str | None = None
    agent: str | None = None
    metadata: dict[str, Any] | None = None


class ConversationSummary(BaseModel):
    """Summary of a conversation for listing."""

    id: str
    title: str
    message_count: int
    last_message_at: datetime
    created_at: datetime


# =============================================================================
# Documents
# =============================================================================


class DocumentUploadResponse(BaseModel):
    """Response after uploading a document."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    filename: str
    format: DocumentFormat
    size_bytes: int
    status: DocumentStatus = DocumentStatus.PENDING
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ExtractedTable(BaseModel):
    """A table extracted from a document."""

    page: int | None = None
    headers: list[str]
    rows: list[list[str]]


class DocumentAnalysisResult(BaseModel):
    """Full analysis result for a document."""

    document_id: str
    filename: str
    format: DocumentFormat
    text: str
    tables: list[ExtractedTable] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    page_count: int | None = None
    word_count: int = 0
    status: DocumentStatus = DocumentStatus.COMPLETED


class DocumentListItem(BaseModel):
    """Document summary for listing."""

    id: str
    filename: str
    format: DocumentFormat
    size_bytes: int
    status: DocumentStatus
    created_at: datetime


# =============================================================================
# SQL
# =============================================================================


class SQLQueryRequest(BaseModel):
    """Natural language query to be converted to SQL."""

    question: str = Field(..., min_length=1, max_length=4_000)
    database: str = "default"


class SQLExecuteRequest(BaseModel):
    """Raw SQL query for direct execution."""

    sql: str = Field(..., min_length=1, max_length=10_000)
    database: str = "default"


class SQLQueryResult(BaseModel):
    """Result of executing a SQL query."""

    question: str
    generated_sql: str
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    explanation: str
    execution_time_ms: float


class ColumnInfo(BaseModel):
    """Information about a single table column."""

    name: str
    type: str
    nullable: bool = True
    primary_key: bool = False
    foreign_key: str | None = None


class TableInfo(BaseModel):
    """Information about a single database table."""

    name: str
    columns: list[ColumnInfo]
    row_count: int | None = None


class DatabaseSchema(BaseModel):
    """Schema information for a database."""

    database: str
    tables: list[TableInfo]


class DatabaseConnectionRequest(BaseModel):
    """Request to connect to a new database."""

    name: str = Field(..., min_length=1, max_length=100)
    url: str = Field(..., min_length=1)


# =============================================================================
# RAG
# =============================================================================


class RAGIngestRequest(BaseModel):
    """Request to ingest a document into the vector store."""

    document_id: str
    collection: str = Field(
        default="documents", min_length=1, max_length=63, pattern=r"^[A-Za-z0-9_-]+$"
    )


class RAGSearchRequest(BaseModel):
    """Semantic search query against the vector store."""

    query: str = Field(..., min_length=1, max_length=4_000)
    collection: str = Field(
        default="documents", min_length=1, max_length=63, pattern=r"^[A-Za-z0-9_-]+$"
    )
    top_k: int = Field(default=5, ge=1, le=50)
    score_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    agent_name: str = Field(default="rag", pattern=r"^[a-z][a-z0-9_]{0,62}$")


class RAGSearchResult(BaseModel):
    """A single search result with source citation."""

    content: str
    score: float
    score_type: str = "cosine"
    source: str
    page: int | None = None
    section: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RAGSearchResponse(BaseModel):
    """Response from a RAG search query."""

    query: str
    results: list[RAGSearchResult]
    total_results: int
    retrieval: dict[str, Any] = Field(default_factory=dict)


class CollectionInfo(BaseModel):
    """Information about a vector store collection."""

    name: str
    document_count: int
    metadata: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Meetings
# =============================================================================


class MeetingCreateRequest(BaseModel):
    """Request containing the single canonical consent receipt."""

    model_config = ConfigDict(extra="forbid")

    consent_policy_version: StrictStr = Field(..., min_length=1, max_length=100)
    consent_attested_at: datetime

    @field_validator("consent_attested_at")
    @classmethod
    def require_aware_consent_time(cls, value: datetime) -> datetime:
        """Require an unambiguous, timezone-aware consent timestamp."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("consent_attested_at must include a timezone")
        return value.astimezone(UTC)


class MeetingResponse(BaseModel):
    """Meeting lifecycle and consent metadata returned by the REST API."""

    model_config = ConfigDict(extra="forbid")

    id: str
    status: MeetingStatus
    consent_policy_version: str
    consent_attested_at: datetime
    started_at: datetime | None = None
    stopped_at: datetime | None = None
    failed_at: datetime | None = None
    failure_reason: str | None = None
    created_at: datetime
    updated_at: datetime
    transcript_segment_count: int = 0
    detected_question_count: int = 0


class MeetingStopResponse(MeetingResponse):
    """Response returned after stopping a meeting."""


class MeetingDeleteResponse(BaseModel):
    """Response returned after deleting a meeting and its child records."""

    model_config = ConfigDict(extra="forbid")

    status: str = "deleted"
    meeting_id: str


class StrictProtocolModel(BaseModel):
    """Base for protocol messages that must reject unknown fields."""

    model_config = ConfigDict(extra="forbid")


class AudioEnvelopeHeader(StrictProtocolModel):
    """Versioned header carried by each binary PCM envelope."""

    protocol: Literal["meeting-audio.v1"]
    meeting_id: StrictStr = Field(..., min_length=1, max_length=256)
    source: AudioSource
    sequence: StrictInt = Field(..., ge=0)
    timestamp_ns: StrictInt = Field(..., gt=0)
    sample_rate_hz: StrictInt = Field(..., ge=8_000, le=96_000)
    channels: StrictInt = Field(..., ge=1, le=2)
    encoding: Literal["pcm_s16le"]
    frame_count: StrictInt = Field(..., ge=1, le=96_000)
    duration_ms: StrictInt = Field(
        ...,
        ge=0,
        le=5_000,
        description="Informational floor(frame_count * 1000 / sample_rate_hz); never used for sizing.",
    )


class MeetingSourceEnded(BaseModel):
    """Client notification that its microphone/source has ended."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["source_ended"]
    source: AudioSource


class MeetingStopCommand(BaseModel):
    """Client command to stop a meeting."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["stop"]


class MeetingStartCommand(BaseModel):
    """Authoritative WebSocket start command."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["start"]


class MeetingStatusEvent(BaseModel):
    """Typed meeting WebSocket status event."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["status"] = "status"
    status: MeetingStatus
    meeting_id: str


class MeetingSourceStatusEvent(BaseModel):
    """Typed state event for one capture source, independent of meeting state."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["source_status"] = "source_status"
    meeting_id: str
    source: AudioSource
    status: Literal["active", "ended"]


class MeetingAudioAck(BaseModel):
    """Acknowledgement for an accepted, sequence-controlled audio frame."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["ack"] = "ack"
    source: AudioSource
    sequence: int
    duplicate: bool = False


class MeetingErrorEvent(BaseModel):
    """Typed meeting WebSocket protocol error."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["error"] = "error"
    code: str
    message: str
    sequence: int | None = None


class MeetingTranscriptEvent(BaseModel):
    """Final source-labelled transcript event."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["transcript"] = "transcript"
    meeting_id: str
    segment_id: str
    source: AudioSource
    text: str
    start_ms: int
    end_ms: int
    final: Literal[True] = True


class MeetingQuestionEvent(BaseModel):
    """Deterministically detected system-source question event."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["question"] = "question"
    meeting_id: str
    question_id: str
    source: Literal["system"] = "system"
    text: str


class MeetingAnswerEvent(BaseModel):
    """Private local answer suggestion event."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["answer"] = "answer"
    meeting_id: str
    question_id: str
    answer: str
    citations: list[str] = Field(default_factory=list)


class MeetingDegradedEvent(BaseModel):
    """Non-terminal degradation event for an optional local dependency."""

    model_config = ConfigDict(extra="forbid")
    type: Literal["degraded"] = "degraded"
    meeting_id: str
    component: Literal["asr", "rag", "ollama"]
    message: str


MeetingClientMessage = Annotated[
    MeetingSourceEnded | MeetingStopCommand | MeetingStartCommand,
    Field(discriminator="type"),
]

MeetingServerEvent = Annotated[
    MeetingStatusEvent
    | MeetingSourceStatusEvent
    | MeetingAudioAck
    | MeetingErrorEvent
    | MeetingTranscriptEvent
    | MeetingQuestionEvent
    | MeetingAnswerEvent
    | MeetingDegradedEvent,
    Field(discriminator="type"),
]


MAX_AUDIO_HEADER_BYTES = 4_096
MAX_AUDIO_PAYLOAD_BYTES = 192_000
MAX_AUDIO_ENVELOPE_BYTES = 4 + MAX_AUDIO_HEADER_BYTES + MAX_AUDIO_PAYLOAD_BYTES


class AudioEnvelopeError(ValueError):
    """Raised when a binary audio envelope violates the meeting contract."""

    def __init__(self, message: str, code: str = "INVALID_AUDIO_ENVELOPE") -> None:
        self.code = code
        super().__init__(message)


def decode_audio_envelope(
    data: bytes,
    expected_meeting_id: str,
    *,
    now_ns: int | None = None,
) -> tuple[AudioEnvelopeHeader, bytes]:
    """Decode and validate one bounded ``header-length + JSON + PCM`` frame.

    The returned PCM bytes remain in memory only and are never persisted by
    the meeting domain.  A strict header and exact payload-size check prevent
    ambiguous framing and unbounded input.
    """
    if len(data) < 4:
        raise AudioEnvelopeError("Audio envelope is missing its header length.", "INVALID_AUDIO_FRAME")
    if len(data) > MAX_AUDIO_ENVELOPE_BYTES:
        raise AudioEnvelopeError("Audio envelope exceeds the maximum frame size.", "AUDIO_FRAME_TOO_LARGE")

    header_length = struct.unpack(">I", data[:4])[0]
    if header_length == 0 or header_length > MAX_AUDIO_HEADER_BYTES:
        raise AudioEnvelopeError("Audio header length is outside the allowed bounds.", "INVALID_AUDIO_HEADER")
    header_end = 4 + header_length
    if len(data) <= header_end:
        raise AudioEnvelopeError("Audio envelope is missing its PCM payload.", "INVALID_AUDIO_FRAME")

    header_bytes = data[4:header_end]
    try:
        header_data = json.loads(header_bytes.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
        header = AudioEnvelopeHeader.model_validate(header_data)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        if isinstance(exc, AudioEnvelopeError):
            raise
        raise AudioEnvelopeError("Audio header is not valid UTF-8 JSON.", "INVALID_AUDIO_HEADER") from exc

    if header.meeting_id != expected_meeting_id:
        raise AudioEnvelopeError("Audio meeting_id does not match the WebSocket session.", "MEETING_ID_MISMATCH")
    if now_ns is not None and header.timestamp_ns > now_ns + 5_000_000_000:
        raise AudioEnvelopeError("Audio timestamp is too far in the future.", "INVALID_AUDIO_TIMESTAMP")
    payload = data[header_end:]
    if len(payload) > MAX_AUDIO_PAYLOAD_BYTES:
        raise AudioEnvelopeError("PCM payload exceeds the maximum size.", "AUDIO_PAYLOAD_TOO_LARGE")
    expected_payload_size = header.frame_count * header.channels * 2
    if len(payload) != expected_payload_size:
        raise AudioEnvelopeError(
            "PCM payload size does not match frame_count and channels.",
            "AUDIO_PAYLOAD_SIZE_MISMATCH",
        )
    return header, payload


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate JSON keys rather than silently choosing one."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AudioEnvelopeError("Audio header contains duplicate JSON keys.", "INVALID_AUDIO_HEADER")
        result[key] = value
    return result


# =============================================================================
# Tools
# =============================================================================


class ToolInfo(BaseModel):
    """Metadata about an available tool."""

    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    agent: AgentType | None = None


class ToolExecuteRequest(BaseModel):
    """Request to manually execute a tool."""

    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolExecuteResponse(BaseModel):
    """Response from manual tool execution."""

    tool_name: str
    output: Any
    duration_ms: float


# =============================================================================
# Health
# =============================================================================


class ServiceHealth(BaseModel):
    """Health status of a single service."""

    name: str
    healthy: bool
    message: str | None = None
    latency_ms: float | None = None
    required_for_meeting: bool = False
    optional_for_answers: bool = False


class HealthResponse(BaseModel):
    """Aggregated health check response."""

    status: str  # "healthy" | "degraded" | "unhealthy"
    services: list[ServiceHealth]
    meeting_ready: bool = False
    version: str = "0.1.0"


# =============================================================================
# Error
# =============================================================================


class ErrorDetail(BaseModel):
    """Structured error response body."""

    code: str
    message: str
    details: dict[str, Any] | None = None
