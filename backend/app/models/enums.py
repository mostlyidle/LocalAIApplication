"""Shared enumerations used across the application."""

from __future__ import annotations

from enum import StrEnum


class AgentType(StrEnum):
    """Identifiers for each specialist agent in the LangGraph orchestrator."""

    CHAT = "chat"
    SQL = "sql"
    DOCUMENT = "document"
    RAG = "rag"
    WEB = "web"


class MessageRole(StrEnum):
    """Chat message roles."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"


class DocumentFormat(StrEnum):
    """Supported document formats for ingestion."""

    PDF = "pdf"
    DOCX = "docx"
    XLSX = "xlsx"
    PPTX = "pptx"
    CSV = "csv"
    HTML = "html"
    MARKDOWN = "markdown"
    TEXT = "text"
    PNG = "png"
    JPG = "jpg"
    JPEG = "jpeg"
    TIFF = "tiff"
    BMP = "bmp"

    @classmethod
    def from_extension(cls, ext: str) -> DocumentFormat:
        """Resolve a file extension (with or without leading dot) to a format."""
        ext = ext.lstrip(".").lower()
        if ext == "md":
            return cls.MARKDOWN
        if ext == "txt":
            return cls.TEXT
        try:
            return cls(ext)
        except ValueError:
            msg = f"Unsupported file extension: .{ext}"
            raise ValueError(msg) from None

    @property
    def is_image(self) -> bool:
        return self in {self.PNG, self.JPG, self.JPEG, self.TIFF, self.BMP}

    @property
    def is_office(self) -> bool:
        return self in {self.DOCX, self.XLSX, self.PPTX}


class DocumentStatus(StrEnum):
    """Processing status for an uploaded document."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class StreamEventType(StrEnum):
    """WebSocket streaming event types for the chat protocol."""

    TOKEN = "token"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    AGENT_SWITCH = "agent_switch"
    ERROR = "error"
    DONE = "done"


class MeetingStatus(StrEnum):
    """Persistence lifecycle for a meeting."""

    CREATED = "created"
    ACTIVE = "active"
    STOPPED = "stopped"
    FAILED = "failed"


class AudioSource(StrEnum):
    """Canonical audio source identifiers used by the desktop capture bridge."""

    MICROPHONE = "microphone"
    SYSTEM = "system"

